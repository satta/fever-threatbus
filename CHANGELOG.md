# Changelog

This changelog documents all notable user-facing changes of
`fever-threatbus`.

Every entry has a category for which we use the following visual abbreviations:

- 🎁 Features
- 🧬 Experimental Features
- ⚠️ Changes
- ⚡️ Breaking Changes
- 🐞 Bug Fixes

## [2021.08.17]

- 🎁 `fever-threatbus` has come to life. This stand-alone application
  connects to Threat Bus via ZeroMQ and bridges the gap between Threat Bus and
  [FEVER](https://github.com/DCSO/fever). `fever-threatbus` maintains a gRPC
  connection with FEVER and adds all received indicators to FEVER's internal
  Bloom filter matcher if they are detectable using that approach.
