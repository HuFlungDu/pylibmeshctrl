=========
Changelog
=========

version 1.2.1
=============

Bugs:
	* Fixed handling of meshcentral's list_devices return with details=True

version 1.2.0
=============

Bugs:
	* Fixed agent sometimes being None causing an oxception
	* Fixed bad code in device_open_url

Features:
	* Changed websockets version to 15. This now uses the proxy implemention from that library, instead of the previous hack.
	* Added lastaddr and lastconnect to list_devices API

version 1.1.2
=============
Bugs:
	* Fixed semver for requirements. New version of websockets broke this library.

Security:
	* Updated cryptogaphy to ~44.0.1 to fix ssl vulnerability.

Version 1.1.1
=============
Bugs:
	* Fixed bug when running device_info when user has access to multiple meshes

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
