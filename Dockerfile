FROM python:3.9
LABEL maintainer="llindstrom@lco.global"

# the exposed port must match the deployment.yaml containerPort value
EXPOSE 80
ENTRYPOINT [ "/usr/local/bin/gunicorn", "hermes_base.wsgi", "-b", "0.0.0.0:80", "--access-logfile", "-", "--error-logfile", "-", "-k", "gevent", "--timeout", "300", "--workers", "2"]

WORKDIR /hermes

COPY requirements.txt /hermes
RUN pip install --upgrade pip && pip install --no-cache-dir -r /hermes/requirements.txt

COPY . /hermes

RUN python manage.py collectstatic --noinput
