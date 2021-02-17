import logging

import click
from rq_scheduler.scheduler import Scheduler
from rq import Queue

from sitesearch.connections import get_rq_redis_client
from sitesearch import keys
from sitesearch import tasks
from sitesearch.config import Config


config = Config()
log = logging.getLogger(__name__)


@click.command()
def scheduler():
    """Run rq-scheduler"""
    redis_client = get_rq_redis_client()
    scheduler = Scheduler(connection=redis_client)
    queue = Queue(connection=redis_client)

    for site in config.sites.values():
        job = queue.enqueue(tasks.index,
                            args=[site],
                            kwargs={
                                "rebuild_index": True,
                                "force": True
                            },
                            job_timeout=tasks.INDEXING_TIMEOUT)

        # Track in-progress indexing tasks in a Redis set, so that we can
        # check if indexing is in-progress. Tasks should remove their
        # IDs from the set, so that when the set is empty, we think
        # indexing is done.
        redis_client.sadd(keys.startup_indexing_job_ids(), job.id)

        # Schedule an indexing job to run every 60 minutes.
        #
        # This performs an update-in-place using the existing RediSearch index.
        #
        # NOTE: We need to define this here, at the time we run this command,
        # because there is no deduplication in the cron() method, and this app has
        # no "exactly once" startup/initialization step that we could use to call
        # code only once.
        scheduler.cron(
            "*/60 * * * *",
            func=tasks.index,
            args=[site],
            kwargs={
                "rebuild_index": False,
                "force": False
            },
            use_local_timezone=True,
            timeout=tasks.INDEXING_TIMEOUT
        )

    redis_client.expire(keys.startup_indexing_job_ids(), tasks.INDEXING_TIMEOUT)

    scheduler.run()
