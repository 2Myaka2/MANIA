"""Lightweight constants for MANIA."""

SCHEMA_VERSION = "0.1"

PER_CONDITION_ARTIFACTS = (
    "nodes.csv",
    "edges.csv",
    "graph.json",
    "centrality.csv",
    "communities.csv",
    "temporal_rin.csv",
    "rg_timeseries.csv",
    "conformational_states.csv",
    "contacts_perframe.parquet",
)

CROSS_CONDITION_ARTIFACTS = (
    "comparison.csv",
    "stats.csv",
)

NODE_COLUMNS = (
    "resid",
    "resname",
    "region",
    "condition",
    "x_ca",
    "y_ca",
    "z_ca",
    "tm_relative_z",
    "rmsf_A",
    "sasa_A2",
    "ss",
    "degree",
    "strength",
    "betweenness",
    "closeness",
    "eigenvector",
    "pagerank",
    "kcore",
    "community_id",
)

EDGE_TYPE_PRIORITY = (
    "backbone",
    "hbond",
    "disulfide",
    "salt_bridge",
    "ionic",
    "cation_pi",
    "aromatic_pi",
    "hydrophobic",
    "vdw",
    "residue_contact",
)

EDGE_COLUMNS = (
    "resid_i",
    "resid_j",
    "edge_type",
    "all_edge_types",
    "n_edge_types",
    "condition",
    "contact_freq",
    "mean_dist_A",
    "std_dist_A",
    "n_episodes",
    "mean_lifetime_frames",
    "max_lifetime_frames",
    "mean_lifetime_ns",
    "max_lifetime_ns",
    "formation_count",
    "breakage_count",
    "first_seen_frame",
    "last_seen_frame",
    "window_cv",
)

GRAPH_REQUIRED_KEYS = (
    "condition",
    "n_nodes",
    "n_edges",
    "directed",
    "schema_version",
    "nodes",
    "edges",
)

CENTRALITY_COLUMNS = (
    "resid",
    "condition",
    "degree",
    "strength",
    "betweenness",
    "closeness",
    "eigenvector",
    "pagerank",
    "kcore",
)

COMMUNITIES_COLUMNS = (
    "resid",
    "condition",
    "community_id",
    "community_size",
    "algorithm",
)

TEMPORAL_RIN_COLUMNS = (
    "window_id",
    "time_start_ps",
    "time_end_ps",
    "condition",
    "n_edges",
    "n_nodes_active",
    "density",
    "window_cv",
)

RG_TIMESERIES_COLUMNS = (
    "frame",
    "time_ps",
    "rg_A",
    "condition",
)

CONFORMATIONAL_STATES_COLUMNS = (
    "frame",
    "time_ps",
    "condition",
    "state_id",
    "cluster_label",
    "rg_A",
    "rmsd_A",
)

CONTACTS_PERFRAME_COLUMNS = (
    "frame",
    "time_ps",
    "resid_i",
    "resid_j",
    "edge_type",
    "dist_A",
    "condition",
)

COMPARISON_COLUMNS = (
    "resid_or_edge_id",
    "metric",
    "normal_value",
    "tumor_value",
    "delta",
    "statistic",
    "p_value",
    "q_value",
    "effect_size",
    "condition_specificity",
)

STATS_COLUMNS = (
    "resid_or_edge_id",
    "metric",
    "test",
    "statistic",
    "p_value",
    "q_value",
    "effect_size",
    "significant",
)

ARTIFACT_COLUMNS = {
    "nodes.csv": NODE_COLUMNS,
    "edges.csv": EDGE_COLUMNS,
    "centrality.csv": CENTRALITY_COLUMNS,
    "communities.csv": COMMUNITIES_COLUMNS,
    "temporal_rin.csv": TEMPORAL_RIN_COLUMNS,
    "rg_timeseries.csv": RG_TIMESERIES_COLUMNS,
    "conformational_states.csv": CONFORMATIONAL_STATES_COLUMNS,
    "contacts_perframe.parquet": CONTACTS_PERFRAME_COLUMNS,
    "comparison.csv": COMPARISON_COLUMNS,
    "stats.csv": STATS_COLUMNS,
}
