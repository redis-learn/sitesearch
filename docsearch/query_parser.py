from redisearch import Query

UNSAFE_CHARS = '[]@+-'


def parse(query):
    # Dash postfixes confuse the query parser.
    query = query.strip()
    query.replace(UNSAFE_CHARS, ' ')
    return Query(query).summarize(
        'body', context_len=10
    ).highlight(
        ('title', 'body', 'section_title')
    ).paging(
        0, 15
    )
