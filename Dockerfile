FROM bcgovimages/von-image:py36-1.16-1

ADD requirements*.txt ./

RUN pip3 install --no-cache-dir \
    -r requirements.txt \
    -r requirements.askar.txt \
    -r requirements.bbs.txt \
    -r requirements.dev.txt

RUN mkdir aries_cloudagent && touch aries_cloudagent/__init__.py
ADD aries_cloudagent/version.py aries_cloudagent/version.py
ADD bin ./bin
ADD README.md ./
ADD setup.py ./

RUN pip3 install --no-cache-dir -e .
ADD aries_cloudagent ./aries_cloudagent

USER root
RUN apt-get -y update && apt-get -y install nginx

EXPOSE 5000

COPY ./deployment/nginx.conf /etc/nginx/conf.d/default.conf
COPY ./deployment/start.sh ./start.sh

ENTRYPOINT ["/bin/bash", "./start.sh"]