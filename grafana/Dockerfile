FROM grafana/grafana:12.3.1

RUN grafana-cli plugins install grafana-clickhouse-datasource && \
    grafana-cli plugins install grafana-lokiexplore-app && \
    grafana-cli plugins install grafana-exploretraces-app && \
    grafana-cli plugins install grafana-pyroscope-app
