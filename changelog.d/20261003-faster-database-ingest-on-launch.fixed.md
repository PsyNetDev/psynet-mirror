Sped up experiment launches and `psynet load` by dropping foreign-key constraints once per database import instead of once per table, which removes about 1,200 schema-reflection queries per launch.
