# MANTIS

Monopix-bAsed Next generation Tracking Instrumentation System

MANTIS provides a graphical user interface for operating and monitoring the TJ-Monopix2 telescope.
It is designed to offer an intuitive workflow for data acquisition, configuration, and live visualization.


# Installation

MANTIS requires access to the tj-monopix2-daq repository.
Clone and install both repositories in editable mode:

```bash
git clone https://github.com/SiLab-Bonn/tj-monopix2-daq.git
cd tj-monopix2-daq
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


# Remote access

Access the GUI remotely using:

```bash
ssh -X username@host_server
```
