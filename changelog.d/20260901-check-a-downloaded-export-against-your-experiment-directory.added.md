Downloaded exports are checked against the identity recorded during preflight
before publication, so replacing a deployment during transfer cannot publish
the wrong archive. Missing manifest identity fields count as a mismatch when
preflight supplied them.
