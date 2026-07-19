from . import ashby, greenhouse

CONNECTORS = {
    "greenhouse": greenhouse.fetch,
    "ashby": ashby.fetch,
}
