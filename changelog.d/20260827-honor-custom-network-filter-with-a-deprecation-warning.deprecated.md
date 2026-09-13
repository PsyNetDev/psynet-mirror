Deprecated ``custom_network_filter`` in favor of ``custom_chain_filter`` on
chain trial makers and ``custom_node_filter`` on static trial makers. Existing
overrides still filter candidates, but construction emits a
``DeprecationWarning``.
