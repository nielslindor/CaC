# Plan

Parent owns the workflow template, version bump and release records. A bounded worker owns the packaged fresh-clone regression. Review the code change and worker evidence, open a pull request, require CI, merge and tag a patch release. Update the existing private manifest to the new workflow, apply it through the engine, push and observe its hosted result. Keep the previous release tag unchanged.
