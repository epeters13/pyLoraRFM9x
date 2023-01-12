# pyLoraRFM9x

This project is a fork of [raspi-lora](https://gitlab.com/the-plant/raspi-lora) project.

pyLoraRFM9x is a interrupt based Python library for using HopeRF RFM95/96/97/98 LoRa radios with a Raspberry Pi. The design was inspired by the [RadioHead](http://www.airspayce.com/mikem/arduino/RadioHead) project that is popular on Arduino-based platforms. Several handy features offered by RadioHead are present here, including encryption, addressing, optional acknowledgments and retransmission. The motivation of this project is to allow Raspberry Pis to communicate with devices using the [RadioHead RF95](http://www.airspayce.com/mikem/arduino/RadioHead/classRH__RF95.html) driver.

This fork fixes bugs in the interrupt handling, and supports both acknowledged and unacknowledged transfers with the use of flags in the packet header.

# Usage
### Installation
Requires Python >= 3.5. [RPi.GPIO](https://pypi.python.org/pypi/RPi.GPIO) and [spidev](https://pypi.python.org/pypi/spidev) will be installed as requirements
```bash
pip install --upgrade pyLoraRFM9x
```

### Wiring
Example wiring for the [HopeRF RFM95W](https://www.hoperf.com/modules/lora/RFM95.html) and the Raspberry Pi:

| RFM module pin    | Raspberry Pi GPIO pin|
|:-----------------:|:--------------------:|
| MISO              | MISO                 |
| MOSI              | MOSI                 |
| NSS/CS            | CE1                  |
| CLK               | SCK                  |
| RESET             | GPIO 25              |
| DIO0              | GPIO 5               |   
| 3.3V              | 3.3V                 |
| GND               | GND                  |

Remember to connect an antenna or a quarter wavelength wire to the RFM modules ANT pin.

### Getting Started
First ensure that SPI is enabled on your Raspberry Pi:
```bash
sudo raspi-config
```
Go to **5 Interfacing Options**, select **P4 SPI** and select **Yes** to enable.

Reboot and verify that you see two devices when writing
```bash
ls -l /dev/spidev*
```
in the terminal.

Next, here is a quick example that sets things up and sends a message:
```python
from pyLoraRFM9x import LoRa, ModemConfig

# This is our callback function that runs when a message is received
def on_recv(payload):
    print("From:", payload.header_from)
    print("Received:", payload.message)
    print("RSSI: {}; SNR: {}".format(payload.rssi, payload.snr))

# Lora object will use spi port 0 and use chip select 1. GPIO pin 5 will be used for interrupts and set reset pin to 25
# The address of this device will be set to 2
lora = LoRa(0, 1, 5, 2, reset_pin = 25, modem_config=ModemConfig.Bw125Cr45Sf128, tx_power=14, acks=True)
lora.on_recv = on_recv

# Send a message to a recipient device with address 10
# Retry sending the message twice if we don't get an  acknowledgment from the recipient
message = "Hello there!"
status = lora.send_to_wait(message, 10, retries=2)
if status is True:
    print("Message sent!")
else:
    print("No acknowledgment from recipient")
```

### Encryption
If you'd like to send and receive encrypted packets, you'll need to install the [PyCrypto](https://www.dlitz.net/software/pycrypto/) package. If you're working with devices running RadioHead with RHEncryptedDriver, I recommend using the AES cipher.
```bash
pip install pycrypto
```

and in your code:
```python
from Crypto.Cipher import AES
crypto = AES.new("my-secret-encryption-key")
```
then pass in `crypto` when instantiating the `LoRa` object:
```python
lora = LoRa(0, 17, 2, crypto=crypto)
```

### Configuration
##### Initialization
```python
LoRa(spiport, channel, interrupt, this_address, reset_pin=reset_pin, freq=915, tx_power=14,
      modem_config=ModemConfig.Bw125Cr45Sf128, acks=False, crypto=None)
```
**`spiport`** SPI interface to use (either 0 or 1, if your LoRa radio if connected to SPI0 or SPI1, respectively)

**`channel`** SPI channel to use (either 0 or 1, if your LoRa radio if connected to CE0 or CE1, respectively)

**`interrupt`** GPIO pin (BCM-style numbering) to use for the interrupt

**`this_address`** The address number (0-254) your device will use when sending and receiving packets.

**`reset_pin`** The pin that resets the module. Defaults to None

**`freq`** Frequency used by your LoRa radio. Defaults to 915Mhz

**`tx_power`** Transmission power level from 5 to 23. Keep this as low as possible. Defaults to 14

**`model_config`** Modem configuration. See [RadioHead docs](http://www.airspayce.com/mikem/arduino/RadioHead/classRH__RF95.html#ab9605810c11c025758ea91b2813666e3). Default to Bw125Cr45Sf128.

**`acks`** If `True`, send an acknowledgment packet when a message is received and wait for an acknowledgment when transmitting a message. This is equivalent to using RadioHead's RHReliableDatagram

**`crypto`** An instance of [PyCrypto Cipher.AES](https://www.dlitz.net/software/pycrypto/api/current/Crypto.Cipher.AES-module.html) (see above example)


##### Other options:
A `LoRa` instance also has the following attributes that can be changed:
- **cad_timeout** Timeout for channel activity detection. Default is 1 second
- **retry_timeout** Time to wait for an acknowledgment before attempting a retry. Defaults to 0.5 seconds
- **wait_packet_sent_timeout** Timeout for waiting for a packet to transmit. Default is 0.5 seconds

##### Methods
###### `send_to_wait(data, header_to, header_flags=0)`
Send a message and block until an acknowledgment is received or a timeout occurs. Returns `True` if successful
- ``data`` Your message. Can be a string or byte string
- ``header_to`` Address of recipient (0-255). If address is 255, the message will be broadcast to all devices and **`send_to_wait`** will return `True` without waiting for acknowledgments
- ``header_flags`` Bitmask that can contain flags specific to your application

###### `send(data, header_to, header_id=0, header_flags=0)`
Similar to `send_to_wait` but does not block or wait for acknowledgments and will always return `True`
- ``data`` Your message. Can be a string or byte string
- ``header_id`` Unique ID of message (0-255)
- ``header_to`` Address of recipient (0-255). If address is 255, the message will be broadcast to all devices
- ``header_flags`` Bitmask that can contain flags specific to your application

###### `set_mode_rx()`
Set radio to RX continuous mode

###### `set_mode_tx()`
Set radio to TX mode

###### `set_mode_idle()`
Set radio to idle (disabling receiving or transmitting)

###### `sleep()`
Set radio to low-power sleep mode

###### `wait_packet_sent()`
Blocks until a packet has finished transmitting. Returns `False` if a timeout occurs

###### `close()`
Cleans up GPIO pins and closes the SPI connection. This should be called when your program exits.


##### Callbacks
`on_recv(payload)` 
Callback function that runs when a message is received
`payload` has the following attributes:
`header_from`, `header_to`, `header_id`, `header_flags`, `message`, `rssi`, `snr`

# Resources
[RadioHead](http://www.airspayce.com/mikem/arduino/RadioHead/) - The RadioHead project. Very useful source of information on working with LoRa radios.

[Forked version of RadioHead for Raspberry Pi](https://github.com/hallard/RadioHead) - A fork of the original RadioHead project that better accommodates the Raspberry Pi. Currently is a few years out of date.

[pySX127x](https://github.com/mayeranalytics/pySX127x) - Another Python LoRa library that allows for a bit more configuration. 

[Adafruit CircuitPython module for the RFM95/6/7/8](https://github.com/adafruit/Adafruit_CircuitPython_RFM9x) - LoRa library for CircuitPython

# Changelog

## 0.9.3
Removed unecessary numpy import

## 0.9.2
Merged martynwheeler's fix for handling ACKS, and  straend's naming

