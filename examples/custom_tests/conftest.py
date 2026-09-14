"""conftest.py for custom test extensions.

This file is optional.  You can define fixtures here that are specific to
your custom tests.  All VIP core fixtures (vip_config, connect_client, etc.)
are available automatically, because VIP registers them as part of its own
pytest plugin (see src/vip/fixtures.py) rather than through a conftest.py of
its own -- so they resolve here regardless of where this directory lives on
disk, not just when it happens to sit under VIP's own test tree.
"""
