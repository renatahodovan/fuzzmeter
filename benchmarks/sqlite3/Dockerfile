FROM parent_image

ARG CACHEBUST=0
RUN echo "CACHEBUST=${CACHEBUST}" >/dev/null

RUN apt-get update && apt-get install -y make autoconf automake libtool curl tcl zlib1g-dev tcl-dev

# We won't be able to poll fossil for changes, so this will build
# only once a day.
RUN mkdir $SRC/sqlite3 && \
    cd $SRC/sqlite3 && \
    curl 'https://www.sqlite.org/src/tarball?uuid=trunk' -o sqlite3.tar.gz && \
    tar xzf sqlite3.tar.gz

WORKDIR $SRC/sqlite3

COPY build.sh $SRC/
COPY benchmark.yaml /benchmark.yaml
COPY grammarinator/ $SRC/grammarinator
COPY sqlite_seed_corpus.zip $OUT/sqlite_seed_corpus.zip
