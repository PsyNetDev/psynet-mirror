Set `GET_SOURCES_ATTEMPTS: 3` in `.gitlab-ci.yml` so CI jobs retry `git fetch` when GitLab's internal `ci-gateway` drops a connection.
