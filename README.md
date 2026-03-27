# cpt

CLI for competitive programming. Creates problem directories with C++ templates, Makefiles, and automatic sample downloading via [Competitive Companion](https://github.com/jmerle/competitive-companion).

## Install

```bash
ln -s ~/cptool/cpt ~/bin/cpt
```

## Usage

```bash
cpt abc                    # create problem, download samples from CC
cpt A B C D E              # create multiple problems, download from CC
cpt abc --no-download      # create without downloading
cpt A B C D E --no-download
```

Inside a problem directory:

```bash
make          # build (debug mode)
make fast     # build (optimized, no debug checks)
make test     # run against sample cases
```

Precompiled headers for `bits/stdc++.h` are built automatically on first `make`.

## Configuration

Config lives in `~/.config/cpt/`:

- `template.cpp` -- C++ template copied into each problem directory
- `config.json` -- optional overrides (e.g. custom template path)
