# Feature: Neo4j Persistence, Graph Routing & OTel Metrics

This feature transitions the server-side persistence from volatile Redis hashes to a permanent graph-based storage using Neo4j, implements dynamic P2P routing, and integrates OpenTelemetry for real-time network health monitoring.

## 1. Permanent Graph Persistence (Neo4j)
- **Infrastructure**: Added Neo4j 5 (Community) to `docker-compose.yml` with data persistence.
- **Peer Registry**: Refactored the peer registry to use Neo4j as the primary source of truth.
    - Peers are now permanent nodes in the graph.
    - `online` status is computed dynamically based on `last_seen` timestamps.
    - Added an explicit `DELETE` endpoint for admin-level peer eviction.
- **Data Model**: Peers are stored as `:Peer` nodes with properties: `peer_id`, `org_id`, `api_url`, `udp_host`, `udp_port`, `group`, and `transport`.

## 2. Graph-Based Routing
- **Metric Collection**: Updated P2P metrics to create `:CONNECTS_TO` edges between peers in the graph.
- **Dynamic Weighting**: Edges store real-time telemetry: `rtt_ms`, `jitter_ms`, and `loss_rate`.
- **Optimal Path Discovery**: Added a routing engine (`/peers/route`) that uses Cypher's `shortestPath` to calculate the best relay path between any two peers in the organization, minimizing total network cost.

## 3. OpenTelemetry (OTel) Metrics
- **Agent Instrumentation**:
    - Integrated the OpenTelemetry SDK with a Prometheus exporter.
    - Exposed a `/metrics` endpoint on each agent.
    - Added custom counters for P2P performance: `rs_transfers_total`, `rs_packets_sent_total`, and `rs_packets_recovered_total`.
    - Auto-instrumented FastAPI for request/response telemetry.
- **Server Proxy**: Implemented a metrics proxy (`GET /peers/{peer_id}/metrics`) that allows the UI to fetch real-time telemetry from any agent via the Control Plane, overcoming CORS and network isolation hurdles.

## 4. Admin Dashboard Enhancements
- **Network Health Tab**: Added a new "Network Health (OTel)" tab to the Admin Panel.
- **Real-time Telemetry**: Administrators can select any online peer and visualize its live Prometheus metrics directly from the interface.
- **Peer Details**: Updated the UI to display peer group and organization context retrieved from the graph.

## 5. Stabilization & Technical Improvements
- **Dependency Management**: Standardized on `uv` for dependency resolution and lockfile management.
- **TypeScript Safety**: Updated frontend interfaces to match the new backend data models.
- **Reliability**: Fixed server-side container initialization by ensuring all new dependencies (Neo4j, httpx) are correctly exported to `requirements.txt`.
