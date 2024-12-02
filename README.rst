.. These are examples of badges you might want to add to your README:
   please update the URLs accordingly

    .. image:: https://api.cirrus-ci.com/github/<USER>/pylibmeshctrl.svg?branch=main
        :alt: Built Status
        :target: https://cirrus-ci.com/github/<USER>/pylibmeshctrl
    .. image:: https://readthedocs.org/projects/pylibmeshctrl/badge/?version=latest
        :alt: ReadTheDocs
        :target: https://pylibmeshctrl.readthedocs.io/en/stable/
    .. image:: https://img.shields.io/coveralls/github/<USER>/pylibmeshctrl/main.svg
        :alt: Coveralls
        :target: https://coveralls.io/r/<USER>/pylibmeshctrl
    .. image:: https://img.shields.io/pypi/v/pylibmeshctrl.svg
        :alt: PyPI-Server
        :target: https://pypi.org/project/pylibmeshctrl/
    .. image:: https://img.shields.io/conda/vn/conda-forge/pylibmeshctrl.svg
        :alt: Conda-Forge
        :target: https://anaconda.org/conda-forge/pylibmeshctrl
    .. image:: https://pepy.tech/badge/pylibmeshctrl/month
        :alt: Monthly Downloads
        :target: https://pepy.tech/project/pylibmeshctrl
    .. image:: https://img.shields.io/twitter/url/http/shields.io.svg?style=social&label=Twitter
        :alt: Twitter
        :target: https://twitter.com/pylibmeshctrl

.. image:: https://img.shields.io/badge/-PyScaffold-005CA0?logo=pyscaffold
    :alt: Project generated with PyScaffold
    :target: https://pyscaffold.org/

|

meshctrl
========

Library for remotely interacting with a
`MeshCentral <https://meshcentral.com/>`__ server instance

Installation
------------

pip install meshctrl

Usage
-----

This module is implemented as a primarily asynchronous library
(asyncio), mostly through the ``Session`` class, which is exported as
default. Because the library is asynchronous, you must wait for it to be
initialized before interacting with the server. The preferred way to do
this is to use the async context manager pattern:

.. code:: python

   import meshctrl

   async with meshctrl.session.Session(url, **options):
       print(await session.list_users())
   ...

However, if you prefer to instantiate the object yourself, you can
simply use the ``initialized`` property:

.. code:: python

   session = meshctrl.session.Session(url, **options)
   await session.initialized.wait()

Note that, in this case, you will be rquired to clean up tho session
using its ``close`` method.

Session Parameters
------------------

``url``: URL of meshcentral server to connect to. Should start with
either "ws://" or "wss://".

``options``: optional parameters. Described at `Read the
Docs <https://pylibmeshctrl.readthedocs.io/en/latest/api/meshctrl.html#module-meshctrl.session>`__

API
---

API is documented in the `API
Docs <https://pylibmeshctrl.readthedocs.io/en/latest/api/meshctrl.htm>`__



.. _pyscaffold-notes:

Note
====

This project has been set up using PyScaffold 4.6. For details and usage
information on PyScaffold see https://pyscaffold.org/.
