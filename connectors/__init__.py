from . import amazon, ashby, google, greenhouse, workday

CONNECTORS = {
    "greenhouse": greenhouse.fetch,
    "ashby": ashby.fetch,
    "google": google.fetch,
    "amazon": amazon.fetch,
    "workday": workday.fetch,
}
