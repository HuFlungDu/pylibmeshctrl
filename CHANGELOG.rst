=========
Changelog
=========

Version 1.1.0
=============
Features:
	* Added overrides for meshcentral files for testing purposes
	* Added `users` field to `device` object

Bugs:
	* Fixed connection errors not raising immediately
	* Fixed run_commands parsing return from multiple devices incorrectly
	* Fixed listening to raw not removing its listener correctly
	* Fixed javascript timecodes not being handled in gnu environments
	* Changed some fstring formatting that locked the library into python >3.13


Version 1.0.0
=============

First release
