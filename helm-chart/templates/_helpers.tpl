{{/* vim: set filetype=mustache: */}}
{{/*
Expand the name of the chart.
*/}}
{{- define "hermes.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "hermes.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "hermes.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Generate the hermes main deploy url
*/}}
{{- define "hermes.mainDeployUrl" -}}
{{- $ingressClass := index .Values.ingress.annotations "kubernetes.io/ingress.class" | quote -}}
{{- $hosts := first .Values.ingress.hosts -}}
{{- $host := pluck "host" $hosts | first -}}
{{- if contains "nginx-ingress-public" $ingressClass -}}
{{- printf "https://%s" $host -}}
{{- else -}}
{{- printf "http://%s" $host -}}
{{- end -}}
{{- end -}}

{{/*
Common labels
*/}}
{{- define "hermes.labels" -}}
app.kubernetes.io/name: {{ include "hermes.name" . }}
helm.sh/chart: {{ include "hermes.chart" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{/*
Create the name of the service account to use
*/}}
{{- define "hermes.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
    {{ default (include "hermes.fullname" .) .Values.serviceAccount.name }}
{{- else -}}
    {{ default "default" .Values.serviceAccount.name }}
{{- end -}}
{{- end -}}

{{/*
Generate the postgres DB hostname
*/}}
{{- define "hermes.dbhost" -}}
{{- if .Values.postgresql.fullnameOverride -}}
{{- .Values.postgresql.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else if .Values.useDockerizedDatabase -}}
{{- printf "%s-postgresql" .Release.Name -}}
{{- else -}}
{{- required "`postgresql.hostname` must be set when `useDockerizedDatabase` is `false`" .Values.postgresql.hostname -}}
{{- end -}}
{{- end -}}

{{/*
Generate the cache location
*/}}
{{- define "hermes.cacheLocation" -}}
{{- if not .Values.redis.enabled -}}
{{- required "Must set `redisURL`" .Values.redisURL -}}
{{- else if .Values.redis.fullnameOverride -}}
{{- printf "redis://%s-master:%s/0" .Values.redis.fullnameOverride .Values.redis.master.port -}}
{{- else -}}
{{- printf "redis://%s-redis-master:%s/0" .Release.Name .Values.redis.master.port -}}
{{- end -}}
{{- end -}}

{{/*
Create the environment variables for configuration of this project. They are
repeated in a bunch of places, so to keep from repeating ourselves, we'll
build it here and use it everywhere.
*/}}
{{- define "hermes.extraEnv" -}}
- name: HOME
  value: "/tmp"
- name: DEBUG
  value: {{ .Values.djangoDebug | quote }}
- name: SAVE_TEST_MESSAGES
  value: {{ .Values.saveTestMessages | quote }}
- name: CACHE_BACKEND
  value: {{ .Values.cacheBackend | quote }}
- name: CACHE_LOCATION
  value: {{ include "hermes.cacheLocation" . | quote }}
- name: HERMES_FRONT_END_BASE_URL
  value: {{ .Values.hermesFrontEndBaseUrl | quote }}
- name: HOP_AUTH_BASE_URL
  value: {{ .Values.hopAuthBaseUrl | quote }}
- name: GCN_CLASSIC_OVER_KAFKA_GROUP_ID
  value: {{ .Values.brokers.gcnClassicOverKafka.groupId | quote }}
- name: HOPSKOTCH_GROUP_ID
  value: {{ .Values.brokers.hopskotch.groupId | quote }}
- name: GCN_EMAIL
  value: {{ .Values.gcnEmail }}
{{- end }}

{{/*
Define shared database environment variables
*/}}
{{- define "hermes.backendEnv" -}}
- name: DB_HOST
  value: {{ include "hermes.dbhost" . | quote }}
- name: DB_NAME
  value: {{ .Values.postgresql.auth.database | quote }}

{{/* This removed when hermes db moved to AWS RDS and DB_PASS became k8s secret
- name: DB_PASS
  value: {{ .Values.postgresql.auth.password | quote }}
*/}}

- name: DB_USER
  value: {{ .Values.postgresql.auth.username | quote }}
- name: DB_PORT
  value: {{ .Values.postgresql.primary.service.port.postgresql | quote }}
- name: SECRET_KEY
  value: {{ .Values.secretKey | quote }}
{{- end -}}
