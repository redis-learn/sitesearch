import concurrent.futures
import json
from dataclasses import asdict
from typing import List, Tuple, Callable

import redis.exceptions
from redis import Redis
from redisearch import TextField, Client
from bs4 import BeautifulSoup, element

from docsearch.errors import ParseError
from docsearch.models import SearchDocument, TYPE_PAGE, TYPE_SECTION
from docsearch.scorers import boost_sections
from docsearch.validators import skip_release_notes

ROOT_PAGE = "Redis Labs Documentation"

DEFAULT_VALIDATORS = (
    skip_release_notes,
)

DEFAULT_SCORERS = (
    boost_sections,
)

DEFAULT_SCHEMA = (
    TextField("title", weight=5),
    TextField("section_title", weight=1.2),
    TextField("body"),
    TextField("url"),
)

ScorerList = List[Callable[[SearchDocument, float], float]]


def prepare_text(text: str) -> str:
    return text.strip().strip("\n").replace("\n", " ")


def extract_parts(doc, h2s: List[element.Tag]) -> List[SearchDocument]:
    """
    Extract SearchDocuments from H2 elements in a SearchDocument.

    Given a list of H2 elements in a page, we extract the HTML content for
    that "part" of the page by grabbing all of the sibling elements and
    converting them to text.
    """
    docs = []

    def next_element(elem):
        """Get sibling elements until we exhaust them."""
        while elem is not None:
            elem = elem.next_sibling
            if hasattr(elem, 'name'):
                return elem

    for i, tag in enumerate(h2s):
        # Sometimes we stick the title in as a link...
        if tag and tag.string is None:
            tag = tag.find("a")

        part_title = tag.get_text() if tag else ""

        page = []
        elem = next_element(tag)

        while elem and elem.name != 'h2':
            page.append(str(elem))
            elem = next_element(elem)

        body = prepare_text(
            BeautifulSoup('\n'.join(page), 'html.parser').get_text())
        _id = f"{doc.url}:{doc.title}:{part_title}:{i}"

        docs.append(SearchDocument(
            doc_id=_id,
            title=doc.title,
            hierarchy=doc.hierarchy,
            section_title=part_title or "",
            body=body,
            url=doc.url,
            type=TYPE_SECTION,
            position=i))

    return docs


def extract_hierarchy(soup):
    """
    Extract the page hierarchy we need from the page's breadcrumbs:
    root and parent page.

    E.g. for the breadcrumbs:
            RedisInsight > Using RedisInsight > Cluster Management

    We want:
            ["RedisInsight", "Using RedisInsight", "Cluster Management"]
    """
    return [a.get_text() for a in soup.select("#breadcrumbs a")
            if a.get_text() != ROOT_PAGE]


def prepare_document(html: str) -> List[SearchDocument]:
    """
    Break an HTML string up into a list of SearchDocuments.

    If the document has any H2 elements, it is broken up into
    sub-documents, one per H2, in addition to a 'page' document
    that we index with the entire content of the page.
    """
    docs = []
    soup = BeautifulSoup(html, 'html.parser')

    try:
        title = prepare_text(soup.title.string.split("|")[0])
    except AttributeError:
        raise (ParseError(f"Failed -- missing title"))

    try:
        url = soup.find_all("link", attrs={"rel": "canonical"})[0].attrs['href']
    except IndexError:
        raise ParseError(f"Failed -- missing link")

    hierarchy = extract_hierarchy(soup)

    if not hierarchy:
        raise ParseError(f"Failed -- missing breadcrumbs")

    content = soup.select(".main-content")

    # Try to index only the content div. If a page lacks
    # that div, index the entire thing.
    if content:
        content = content[0]
    else:
        content = soup

    h2s = content.find_all('h2')
    body = prepare_text(content.get_text())
    doc = SearchDocument(
        doc_id=f"{url}:{title}",
        title=title,
        section_title="",
        hierarchy=hierarchy,
        body=body,
        url=url,
        type=TYPE_PAGE)

    # Index the entire document
    docs.append(doc)

    # If there are headers, break up the document and index each header
    # as a separate document.
    if h2s:
        docs += extract_parts(doc, h2s)

    return docs


def document_to_dict(document: SearchDocument, scorers: ScorerList):
    """
    Given a SearchDocument, return a dictionary of the fields to index,
    and options like the ad-hoc score.

    Every callable in "scorers" is given a chance to influence the ad-hoc
    score of the document.

    At query time, RediSearch will multiply the ad-hoc score by the TF*IDF
    score of a document to produce the final score.
    """
    score = 1.0
    for scorer in scorers:
        score = scorer(document, score)
    doc = asdict(document)
    doc['score'] = score
    doc['hierarchy'] = json.dumps(doc['hierarchy'])
    return doc


def add_document(search_client, doc: SearchDocument, scorers: ScorerList):
    """
    Add a document to the search index.

    This is the moment we convert a SearchDocument into a Python
    dictionary and send it to RediSearch.
    """
    search_client.add_document(**document_to_dict(doc, scorers))


def prepare_file(file) -> List[SearchDocument]:
    print(f"parsing file {file}")
    with open(file, encoding="utf-8") as f:
        return prepare_document(f.read())


class Indexer:
    def __init__(self, search_client: Client, redis_client: Redis,
                 schema=None, validators=None, scorers=None,
                 create_index=True):
        self.search_client = search_client
        self.redis_client = redis_client

        if validators is None:
            self.validators = DEFAULT_VALIDATORS

        if scorers is None:
            self.scorers = DEFAULT_SCORERS

        if schema is None:
            self.schema = DEFAULT_SCHEMA

        if create_index:
            self.setup_index()

    def setup_index(self):
        # Creating the index definition and schema
        try:
            self.search_client.info()
        except redis.exceptions.ResponseError:
            pass
        else:
            self.search_client.drop_index()

        self.search_client.create_index(self.schema)

    def validate(self, doc: SearchDocument):
        for v in self.validators:
            v(doc)

    def prepare_files(self, files: List[str]) -> Tuple[List[SearchDocument], List[str]]:
        docs: List[SearchDocument] = []
        errors: List[str] = []

        with concurrent.futures.ProcessPoolExecutor() as executor:
            futures = []

            for file in files:
                futures.append(executor.submit(prepare_file, file))

            for future in concurrent.futures.as_completed(futures):
                try:
                    docs_for_file = future.result()
                except ParseError as e:
                    errors.append(f"{e}: {file}")
                    continue

                if not docs_for_file:
                    continue

                # If any document we generated for a file fails validation, we
                # intentionally skip the entire file -- the "continue" here
                # applies to the loop over completed futures.
                try:
                    for doc in docs_for_file:
                        self.validate(doc)
                except ParseError as e:
                    errors.append(f"{e}: {file}")
                    continue

                docs += docs_for_file

        return docs, errors

    def index_files(self, files: List[str]) -> List[str]:
        docs, errors = self.prepare_files(files)

        with concurrent.futures.ThreadPoolExecutor() as executor:
            futures = []

            for doc in docs:
                futures.append(
                    executor.submit(add_document, self.search_client, doc, self.scorers))

            for future in concurrent.futures.as_completed(futures):
                try:
                    future.result()
                except redis.exceptions.DataError as e:
                    errors.append(f"Failed -- bad data: {e}")
                    continue
                except redis.exceptions.ResponseError as e:
                    errors.append(f"Failed -- response error: {e}")
                    continue

        return errors
