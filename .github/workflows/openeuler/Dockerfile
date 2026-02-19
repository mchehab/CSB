# syntax=docker/dockerfile:1
#
# Base image
#
ARG BASE_IMAGE=openeuler/openeuler:24.03-lts-sp3
ARG TARGET=amd64

FROM ${BASE_IMAGE}

#
# To create and run it direcly, use:
#    docker build -t openeuler-csb:latest -f .github/workflows/openeuler/Dockerfile .
#    docker run -v /var/run/docker.sock:/var/run/docker.sock -it openeuler-csb:latest bash
#
# Note, however, that csb is currently not ready to run like that
#


# Needed volumes. The first two are used by get info scripts
VOLUME [ "/boot", "/lib/modules", "/var/run/docker.sock" ]

RUN dnf install -y moby-engine moby-client

# Create a working directory and update submodules
WORKDIR /root/csb
COPY . .

CMD ["/root/csb/run.sh"]
