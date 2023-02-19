FROM python:3.10

RUN pip install poetry

RUN mkdir /workspace
WORKDIR /workspace

COPY pyproject.toml poetry.lock ./
RUN poetry config virtualenvs.create false \
    && poetry install --no-dev --no-interaction --no-ansi --no-root

COPY minimal_amcrest/ ./minimal_amcrest

ENTRYPOINT [ "python3", "-m", "minimal_amcrest" ]
CMD [ "-c", "/config.toml" ]
