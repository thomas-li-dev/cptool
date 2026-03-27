# cptool

CLI tool for competitive programming. Sets up problem/contest directories with C++ templates, Makefiles, and automatic sample downloading via the [Competitive Companion](https://github.com/jmerle/competitive-companion) browser extension.

## Install

```bash
# Symlink into your PATH
ln -s ~/cptool/cpt ~/bin/cpt
ln -s ~/cptool/cptool ~/bin/cptool

# Enable tab completion (add to ~/.zshrc or ~/.bashrc)
eval "$(cpt completion zsh)"

# Build precompiled headers (optional, ~3x faster compilation)
cpt pch
```

## Usage

```bash
# Create a problem (downloads samples from Competitive Companion)
cpt problem abc

# Create a problem without downloading
cpt problem abc --no-download

# Create a contest (downloads all problems from Competitive Companion)
cpt contest cf2000

# Create a contest without downloading
cpt contest cf2000 --no-download --count 5
```

Inside a problem directory:

```bash
make          # build (debug mode)
make fast     # build (optimized, no debug checks)
make test     # run against sample cases
```

Precompiled headers for `bits/stdc++.h` are built automatically on first `make` if not already present.

## Configuration

Config lives in `~/.config/cptool/`:

- `template.cpp` -- C++ template copied into each problem directory
- `config.json` -- optional overrides (e.g. custom template path)

## Project structure

```
cptool              # main CLI script
cpt                 # symlink to cptool
Makefile.template   # template for per-problem Makefiles
template.cpp        # default C++ template
test_cptool.py      # test suite
```
