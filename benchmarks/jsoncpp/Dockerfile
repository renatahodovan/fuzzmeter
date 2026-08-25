FROM parent_image

ARG CACHEBUST=0
RUN echo "CACHEBUST=${CACHEBUST}" >/dev/null

RUN git clone https://github.com/open-source-parsers/jsoncpp $SRC/jsoncpp
WORKDIR $SRC/jsoncpp

COPY build.sh $SRC/
COPY benchmark.yaml /benchmark.yaml
COPY grammarinator/ $SRC/grammarinator
COPY jsoncpp_seed_corpus.zip "${OUT}/jsoncpp_seed_corpus.zip"
