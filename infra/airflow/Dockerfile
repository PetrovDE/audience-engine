FROM apache/airflow:3.1.8-python3.11

USER airflow
COPY --chown=airflow:0 airflow/requirements-airflow.txt /requirements-airflow.txt
RUN pip install --no-cache-dir --user --requirement /requirements-airflow.txt
