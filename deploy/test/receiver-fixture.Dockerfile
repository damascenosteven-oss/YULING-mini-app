# Disposable integration host only; never used for the application or a real server.
FROM docker:29.8.0-cli@sha256:eccaacfeed644c7de222ff047483568cb988dde95476fbaaf10ea2d04921bb66 AS cli
FROM python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f
COPY --from=cli /usr/local/bin/docker /usr/bin/docker-real
COPY deploy/test/fixture-docker.sh /usr/bin/docker
RUN chmod 755 /usr/bin/docker
RUN sed -i 's|http://|https://|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends openssh-server sudo \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --create-home --shell /bin/sh yuling-ppt-deploy \
    && mkdir -p /run/sshd /opt/yuling-ppt-test /etc/yuling-ppt-test /usr/local/libexec \
    && chmod 700 /opt/yuling-ppt-test /etc/yuling-ppt-test \
    && ln -s /usr/local/bin/python3 /usr/bin/python3 \
    && printf 'yuling-ppt-deploy ALL=(root) NOPASSWD: /usr/bin/python3 -I /usr/local/libexec/yuling-ppt-release.py\n' > /etc/sudoers.d/ppt-fixture \
    && chmod 440 /etc/sudoers.d/ppt-fixture \
    && visudo -cf /etc/sudoers.d/ppt-fixture
COPY deploy/test/release.py /usr/local/libexec/yuling-ppt-release.py
RUN chmod 755 /usr/local/libexec/yuling-ppt-release.py
CMD ["/usr/sbin/sshd", "-D", "-e"]
