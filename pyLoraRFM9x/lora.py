import time
from enum import Enum
import math
from collections import namedtuple
from random import random

import RPi.GPIO as GPIO
import spidev

import threading

from .constants import *


class ModemConfig(Enum):
    Bw125Cr45Sf128 = (0x72, 0x74, 0x04) # Radiohead default
    Bw500Cr45Sf128 = (0x92, 0x74, 0x04)
    Bw31_25Cr48Sf512 = (0x48, 0x94, 0x04)
    Bw125Cr48Sf4096 = (0x78, 0xc4, 0x0c)


class LoRa(object):
    def __init__(self, channel, interrupt, this_address, reset_pin=None, freq=915, tx_power=14,
                 modem_config=ModemConfig.Bw125Cr45Sf128, receive_all=False,
                 acks=False, crypto=None, default_mode = 0):
        """
        Lora((channel, interrupt, this_address, freq=915, tx_power=14,
                 modem_config=ModemConfig.Bw125Cr45Sf128, receive_all=False,
                 acks=False, crypto=None, reset_pin=False)
        channel: SPI channel [0 for CE0, 1 for CE1]
        interrupt: Raspberry Pi interrupt pin (BCM)
        this_address: set address for this device [0-254]
        reset_pin: the Raspberry Pi port used to reset the RFM9x if connected
        freq: frequency in MHz
        tx_power: transmit power in dBm
        modem_config: Check ModemConfig. Default is compatible with the Radiohead library
        receive_all: if True, don't filter packets on address
        acks: if True, request acknowledgments
        crypto: if desired, an instance of pycrypto AES
        default_mode: Default mode the modem enters after transmit [0: RXCONTINUOUS, 1: IDLE, 2: SLEEP] default: RXCONTINUOUS
        """
            

        self._spiport = spiport
        self._channel = channel
        self._interrupt = interrupt
        self._hw_lock = threading.RLock() # lock for multithreaded access

        self._mode = None
        self._cad = None
        self._freq = freq
        self._tx_power = tx_power
        self._modem_config = modem_config
        self._receive_all = receive_all
        self._acks = acks

        self._this_address = this_address
        self._last_header_id = 0

        self._last_payload = None
        self.crypto = crypto

        self.cad_timeout = 0
        self.send_retries = 2
        self.wait_packet_sent_timeout = 0.2
        self.retry_timeout = 0.2

        # default mode after CAD_DONE and TX_DONE events
        if default_mode == 0:
            self._set_default_mode = self.set_mode_rx
        elif default_mode == 1:
            self._set_default_mode = self.set_mode_idle
        elif default_mode == 2:
            self._set_default_mode = self.set_mode_sleep
        else:
            raise ValueError(f"Invalid default mode: {default_mode}")
        
        # Setup the module
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self._interrupt, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
        GPIO.add_event_detect(self._interrupt, GPIO.RISING, callback=self._handle_interrupt)

        # reset the board
        if reset_pin:
            GPIO.setup(reset_pin,GPIO.OUT)
            GPIO.output(reset_pin,GPIO.LOW)
            time.sleep(0.01)
            GPIO.output(reset_pin,GPIO.HIGH)
            time.sleep(0.01)

        
        self.spi = spidev.SpiDev()
        self.spi.open(0, self._channel)
        self.spi.max_speed_hz = 5000000

        self._spi_write(REG_01_OP_MODE, MODE_SLEEP | LONG_RANGE_MODE)
        time.sleep(0.1)

        assert self._spi_read(REG_01_OP_MODE) == (MODE_SLEEP | LONG_RANGE_MODE), \
            "LoRa initialization failed"

        self._spi_write(REG_0E_FIFO_TX_BASE_ADDR, 0)
        self._spi_write(REG_0F_FIFO_RX_BASE_ADDR, 0)

        self.set_mode_idle()

        # set modem config (Bw125Cr45Sf128)
        self._spi_write(REG_1D_MODEM_CONFIG1, self._modem_config.value[0])
        self._spi_write(REG_1E_MODEM_CONFIG2, self._modem_config.value[1])
        self._spi_write(REG_26_MODEM_CONFIG3, self._modem_config.value[2])

        # set preamble length (8)
        self._spi_write(REG_20_PREAMBLE_MSB, 0)
        self._spi_write(REG_21_PREAMBLE_LSB, 8)

        # set frequency
        frf = int((self._freq * 1000000.0) / FSTEP)
        self._spi_write(REG_06_FRF_MSB, (frf >> 16) & 0xff)
        self._spi_write(REG_07_FRF_MID, (frf >> 8) & 0xff)
        self._spi_write(REG_08_FRF_LSB, frf & 0xff)

        # Set tx power
        if self._tx_power < 5:
            self._tx_power = 5
        if self._tx_power > 23:
            self._tx_power = 23

        if self._tx_power > 20:
            self._spi_write(REG_4D_PA_DAC, PA_DAC_ENABLE)
            self._tx_power -= 3
        else:
            self._spi_write(REG_4D_PA_DAC, PA_DAC_DISABLE)

        self._spi_write(REG_09_PA_CONFIG, PA_SELECT | (self._tx_power - 5))

    def on_recv(self, message):
        # This should be overridden by the user
        pass

    def set_mode_sleep(self):
        if self._mode != MODE_SLEEP:
            with self._hw_lock:
                self._spi_write(REG_01_OP_MODE, MODE_SLEEP)
                self._mode = MODE_SLEEP


    def set_mode_tx(self):
        if self._mode != MODE_TX:
            with self._hw_lock:
                self._spi_write(REG_01_OP_MODE, MODE_TX)
                self._spi_write(REG_40_DIO_MAPPING1, 0x40)  # Interrupt on TxDone on DIO0 (01 in bits 7-6 (table 63))
                self._mode = MODE_TX
                
    def set_mode_rx(self):
        if self._mode != MODE_RXCONTINUOUS:
            with self._hw_lock:
                self._spi_write(REG_01_OP_MODE, MODE_RXCONTINUOUS)
                self._spi_write(REG_40_DIO_MAPPING1, 0x00)  # Interrupt on RxDone on DIO0 (00 in bits 7-6 (table 63))
                self._mode = MODE_RXCONTINUOUS

    def set_mode_cad(self):
        if self._mode != MODE_CAD:
            with self._hw_lock:
                self._spi_write(REG_01_OP_MODE, MODE_CAD)
                self._spi_write(REG_40_DIO_MAPPING1, 0x80)  # Interrupt on CadDone on DIO0 (10 in bits 7-6 (table 63))
                self._mode = MODE_CAD

    def _is_channel_active(self):
        self.set_mode_cad()
        while self._mode == MODE_CAD:
            yield

        return self._cad

    def wait_cad(self):
        if not self.cad_timeout:
            return False

        start = time.time()
        for status in self._is_channel_active():
            if time.time() - start > self.cad_timeout:
                return True

            if status is None:
                time.sleep(0.1)
                continue
            else:
                return status

    def wait_packet_sent(self):
        # wait for `_handle_interrupt` to switch the mode back
        start = time.time()
        while time.time() - start < self.wait_packet_sent_timeout:
            if self._mode != MODE_TX:
                return True

        return False

    def set_mode_idle(self):
        if self._mode != MODE_STDBY:
            with self._hw_lock:
                self._spi_write(REG_01_OP_MODE, MODE_STDBY)
                self._mode = MODE_STDBY


    def send(self, data, header_to, header_id=0, header_flags=0):
        """
        The TX FIFO can only be filled in stand-by or idle mode
        """
        self.wait_packet_sent() # make sure we are not transmitting
        CAD_status = self.wait_cad()  # check for CAD
        if CAD_status == 1:
            return False
        self.set_mode_idle()  # Set mode to idle, so we can start filling the transmit FIFO

        header = [header_to, self._this_address, header_id, header_flags]
        if type(data) == int:
            data = [data]
        elif type(data) == bytes:
            data = [p for p in data]
        elif type(data) == str:
            data = [ord(s) for s in data]

        if self.crypto:
            data = [b for b in self._encrypt(bytes(data))]

        payload = header + data
        with self._hw_lock:
            self._spi_write(REG_0D_FIFO_ADDR_PTR, 0)
            self._spi_write(REG_00_FIFO, payload)
            self._spi_write(REG_22_PAYLOAD_LENGTH, len(payload))

        self.set_mode_tx()
        return self.wait_packet_sent() # wait for the send interrupt to trigger
        

    def send_to_wait(self, data, header_to, header_flags=0, retries=3):
        self._last_header_id = (self._last_header_id + 1) & 0xFF
        # print(f'sending {data} to {header_to}')
        for _ in range(retries + 1):
            if self._acks:
                header_flags |= FLAGS_REQ_ACK
            success = self.send(data, header_to, header_id=self._last_header_id, header_flags=header_flags)
            if success == False:
                # transmit failed (likely due to CAD)
                continue
            if (not self._acks) or (header_to == BROADCAST_ADDRESS):  # Don't wait for acks from a broadcast message
                return True
            # print(f'sending {data} to {header_to}')

            start = time.time()
            while time.time() - start < self.retry_timeout + (self.retry_timeout * random()):
                if self._last_payload:
                    if self._last_payload.header_to == self._this_address and \
                            self._last_payload.header_flags & FLAGS_ACK and \
                            self._last_payload.header_id == self._last_header_id:

                        # We got an ACK
                        return True
        return False

    def send_ack(self, header_to, header_id):
        # print('SENT ACK')
        self.send(b'!', header_to, header_id, FLAGS_ACK)
        self.wait_packet_sent()

    def _spi_write(self, register, payload):
        if type(payload) == int:
            payload = [payload]
        elif type(payload) == bytes:
            payload = [p for p in payload]
        elif type(payload) == str:
            payload = [ord(s) for s in payload]
        with self._hw_lock:
            self.spi.xfer([register | 0x80] + payload)

    def _spi_read(self, register, length=1):
        if length == 1:
            with self._hw_lock:
                d = self.spi.xfer([register] + [0] * length)[1]            
            return d
        else:
            with self._hw_lock:
                d = self.spi.xfer([register] + [0] * length)[1:]
            return d

    def _decrypt(self, message):
        decrypted_msg = self.crypto.decrypt(message)
        msg_length = decrypted_msg[0]
        return decrypted_msg[1:msg_length + 1]

    def _encrypt(self, message):
        msg_length = len(message)
        padding = bytes(((math.ceil((msg_length + 1) / 16) * 16) - (msg_length + 1)) * [0])
        msg_bytes = bytes([msg_length]) + message + padding
        encrypted_msg = self.crypto.encrypt(msg_bytes)
        return encrypted_msg

    def _handle_interrupt(self, channel):
        irq_flags = self._spi_read(REG_12_IRQ_FLAGS)

        if self._mode == MODE_RXCONTINUOUS and (irq_flags & RX_DONE):
            with self._hw_lock:
                packet_len = self._spi_read(REG_13_RX_NB_BYTES)
                self._spi_write(REG_0D_FIFO_ADDR_PTR, self._spi_read(REG_10_FIFO_RX_CURRENT_ADDR))

                packet = self._spi_read(REG_00_FIFO, packet_len)
                self._spi_write(REG_12_IRQ_FLAGS, 0xff)  # Clear all IRQ flags

                snr = self._spi_read(REG_19_PKT_SNR_VALUE)
                # RSSI calculation for HopeRF RFM9x modules
                # This is different for Semtech radios, it seems
                rssi = -137 + self._spi_read(REG_1A_PKT_RSSI_VALUE)
                
            if snr > 127:
                snr = (256 - snr) * -1
            snr /= 4

               
            if packet_len >= 4:
                header_to = packet[0]
                header_from = packet[1]
                header_id = packet[2]
                header_flags = packet[3]
                message = bytes(packet[4:]) if packet_len > 4 else b''

                if self._this_address != header_to and BROADCAST_ADDRESS != header_to and self._receive_all is False:
                    return

                if self.crypto and len(message) % 16 == 0:
                    message = self._decrypt(message)

                if  (header_to == self._this_address and header_flags & FLAGS_REQ_ACK and not header_flags & FLAGS_ACK) and not self._ack:
                    self.send_ack(header_from, header_id)

                self.set_mode_rx()

                self._last_payload = namedtuple(
                    "Payload",
                    ['message', 'header_to', 'header_from', 'header_id', 'header_flags', 'rssi', 'snr']
                )(message, header_to, header_from, header_id, header_flags, rssi, snr)

                if not header_flags & FLAGS_ACK:
                    self.on_recv(self._last_payload)

        elif self._mode == MODE_TX and (irq_flags & TX_DONE):
            self._set_default_mode() # configured in init

        elif self._mode == MODE_CAD and (irq_flags & CAD_DONE):
            self._cad = irq_flags & CAD_DETECTED # 0 false, 1 detected
            self._set_default_mode() 
        elif self._mode == MODE_RXCONTINUOUS and (irq_flags & RX_TIMEOUT):
            pass

        self._spi_write(REG_12_IRQ_FLAGS, 0xff)

    def close(self):
        GPIO.cleanup()
        self.spi.close()

    def __del__(self):
        self.close()

