from . import ashby, google, greenhouse

CONNECTORS = {
    "greenhouse": greenhouse.fetch,
    "ashby": ashby.fetch,
    "google": google.fetch,
}
