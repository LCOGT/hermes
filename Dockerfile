FROM python:3.9
LABEL maintainer="llindstrom@lco.global"

RUN apt-get --yes update && apt-get --yes install binutils libproj-dev gdal-bin

# the exposed port must match the deployment.yaml containerPort value
EXPOSE 80
ENTRYPOINT [ "/usr/local/bin/gunicorn", "hermes_base.wsgi", "-b", "0.0.0.0:80", "--access-logfile", "-", "--error-logfile", "-", "-k", "gevent", "--timeout", "300", "--workers", "2"]

WORKDIR /hermes

COPY requirements.txt /hermes
RUN pip install --upgrade pip && pip install --no-cache-dir -r /hermes/requirements.txt
RUN pip install gunicorn[gevent]==20.0.4

COPY . /hermes

RUN python manage.py collectstatic --noinput
