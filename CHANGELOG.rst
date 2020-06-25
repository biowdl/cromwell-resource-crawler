==========
Changelog
==========

.. Newest changes should be on top.

.. This document is user facing. Please word the changes in such a way
.. that users understand how the changes affect the new version.

Version 0.1.0-dev
---------------------------
+ Skip directories where ``rc`` file is not present and thus have not yet
  finished executing.
+ Implemented local and slurm backends.
+ Create a structure that allows for adding multiple backends later.
+ Allow json and tsv output
+ Initialized cromwell-resource-crawler
