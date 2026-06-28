# syntax=docker/dockerfile:1.7
FROM parent_image

ENV SRC=/src
ENV WORK=/work
ENV OUT=/out

WORKDIR ${SRC}
