import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()
    
setuptools.setup(
    name='pyLoraRFM9x',
    version='0.9.1',
    packages=setuptools.find_packages(),
    url='https://github.com/mugpahug/pyLoraRFM9x',
    license='MIT',
    author='Edwin Peters',
    author_email='edwin.g.w.peters@gmail.com',
    description='Interrupt driven LoRa RFM9x library for Raspberry Pi inspired by RadioHead',
    long_description=long_description,
    long_description_content_type="text/markdown",
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'Topic :: Software Development :: Libraries',
        'Topic :: System :: Hardware',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.5',
    ],
    keywords='lora rfm95 rfm9x rfm96 rfm97 rfm98 hardware raspberrypi',
    install_requires=[
        'RPi.GPIO',
        'spidev'],
)
