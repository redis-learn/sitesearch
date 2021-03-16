import logging

import newrelic
from falcon.status_codes import HTTP_503
from redis.exceptions import ResponseError

from sitesearch import keys
from sitesearch.config import Config
from sitesearch.connections import get_search_connection, get_rq_redis_client
from .resource import Resource

config = Config()
search_client = get_search_connection(config.default_search_site.index_alias)
log = logging.getLogger(__name__)


class HealthCheckResource(Resource):
    def on_get(self, req, resp):
        """
        This service is considered unhealthy if the default search index is unavailable.
        """
        newrelic.agent.ignore_transaction(flag=True)
        try:
            search_client.info()
        except ResponseError as e:
            # The index doesn't exist -- this may indicate that indexing
            # hasn't started yet, or else our indexing tasks all failed.
            log.error("Response error: %s", e)
            resp.status = HTTP_503
