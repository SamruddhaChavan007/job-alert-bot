from . import amazon, ashby, google, greenhouse, lever, workday

CONNECTORS = {
    "greenhouse": greenhouse.fetch,
    "ashby": ashby.fetch,
    "google": google.fetch,
    "amazon": amazon.fetch,
    "workday": workday.fetch,
    "lever": lever.fetch,
}
