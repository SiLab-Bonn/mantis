# MANTIS

Monopix-bAsed Next generation Tracking Instrumentation System

MANTIS provides a graphical user interface for operating and monitoring the TJ-Monopix2 telescope.
It is designed to offer an intuitive workflow for data acquisition, configuration, and live visualization.

For more information about MANTIS take a look at the [wiki](https://github.com/SiLab-Bonn/mantis/wiki/MANTIS).

# Installation

MANTIS requires access to the tj-monopix2-daq and basil repository.
Clone and install both repositories in editable mode:

```bash
git clone https://github.com/SiLab-Bonn/tj-monopix2-daq.git
cd tj-monopix2-daq
pip install -e .
```
```bash
git clone https://github.com/SiLab-Bonn/basil.git
cd basil
pip install -e .
```
```bash
git clone https://github.com/SiLab-Bonn/mantis.git
cd mantis
pip install -e .
```


# Usage

Launch the graphical user interface with:

```bash
mantisgui

```

## Configuration

Change the [user configuration](https://github.com/SiLab-Bonn/mantis/blob/main/mantis/user_configuration.toml) to reflect your setup.


# Remote access

Access the GUI remotely using:

```bash
ssh -X username@host_server
```
