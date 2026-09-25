Asset classes are now named after how the file is made: `FileAsset` (formerly `ExperimentAsset` and `CachedAsset`) and `GeneratedAsset` (formerly `CachedFunctionAsset`), alongside `OnDemandAsset` and `ExternalAsset`. Whether an asset is included in `psynet export` now follows from when it was made rather than from its class: assets stored while the experiment is running, such as recordings and chain-generated stimuli, are exported; assets prepared before launch, which come from the experiment directory and code, are not. On-demand and external assets are never exported. As a result, stimulus files declared in the timeline are no longer exported, and `asset(function)` no longer requires `cache=True` or `on_demand=True`. The `type` column of the exported `assets/manifest.csv` changes accordingly, for example from `psynet.asset.ExperimentAsset` to `psynet.asset.FileAsset`; update any analysis scripts that filter on it.

```python
asset("bier.wav")                 # FileAsset; not exported when declared in the timeline
asset(generate_tone)              # GeneratedAsset; exported only if created during the run
asset(plot_path, parent=trial)    # FileAsset created during the run; exported
```
