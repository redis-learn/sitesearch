import logging
from typing import Optional
from sitesearch.config import AppConfiguration

from rq import get_current_job

from sitesearch import keys
from sitesearch.connections import get_rq_redis_client
from sitesearch.indexer import Indexer
from sitesearch.models import SiteConfiguration

log = logging.getLogger(__name__)

# These constants are used by other modules to refer to the
# state of the `index` task in the queueing/scheduling system.
JOB_NOT_QUEUED = 'not_queued'
JOB_STARTED = 'started'
INDEXING_TIMEOUT = 60*60  # One hour


def index(site: SiteConfiguration, config: Optional[AppConfiguration] = None, force=False):
    redis_client = get_rq_redis_client()
    if config is None:
        config = AppConfiguration()
    indexer = Indexer(site, config)
    indexer.index(force)

    job = get_current_job()
    if job:
        log.info("Removing indexing job ID: %s", job.id)
        redis_client.srem(keys.startup_indexing_job_ids(), job.id)

    return True
