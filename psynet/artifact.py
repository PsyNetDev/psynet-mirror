import json
import os
import shutil
import tempfile
import urllib.parse
import warnings
from datetime import datetime
from pathlib import Path
from typing import Optional

from dallinger.config import get_config
from dominate.tags import a, div, span

from psynet import deployment_info
from psynet.asset import (
    S3Boto3TransferBackend,
    get_s3_client,
    list_files_in_s3_bucket,
)


class ArtifactStorage:
    """
    Manage the storage of artifacts.
    """

    COMMENT_FILE = "comment.txt"
    EXPERIMENT_STATUS_FILE = "experiment_status.json"
    RECRUITMENT_STATUS_FILE = "recruitment_status.json"
    BASIC_DATA_FILE = "basic_data.json"
    EXPORT_FILE = "export.zip"
    # Backward-compatible aliases.
    PSYNET_EXPORT_FILE = EXPORT_FILE
    DATABASE_EXPORT_FILE = EXPORT_FILE

    DEPLOYMENT_FOLDER = "deployments"
    ARCHIVE_FOLDER = "archive"

    def __init__(self, root: str):
        """
        Initialize the ArtifactStorage with a root directory.

        Parameters
        ----------
        root : str
            Root directory where artifacts will be stored.
        """
        self.root = root

    @property
    def experiment(self):
        from psynet.experiment import get_experiment

        return get_experiment()

    def list_subfolders(self, path: str) -> list:
        """
        List the subfolders in the specified path (non-recursive).

        Parameters
        ----------
        path : str
            Path to the folder to be listed.

        Returns
        -------
        list
            List of subfolders in the specified path sorted by modification time (most recent first).
        """
        raise NotImplementedError

    def download(self, source: str, destination: str):
        """
        Download an artifact from the storage.

        Parameters
        ----------
        source : str
            Path to the artifact in the storage, expressed relative to the root of the storage.
        destination : str
            Local path where the artifact should be downloaded.
        """
        raise NotImplementedError

    def upload(self, source: str, destination: str):
        """
        Upload an artifact to the storage.

        Parameters
        ----------
        source : str
            Local path to the artifact to upload.
        destination : str
            Path in the storage where the artifact should be uploaded, expressed relative to the root of the storage.
        """
        raise NotImplementedError("This method should be implemented in subclasses.")

    def move_file(self, source: str, target: str):
        """
        Move a file to a new location in the storage.

        Parameters
        ----------
        source : str
            Old path in the storage, expressed relative to the root of the storage.
        target : str
            New path in the storage, expressed relative to the root of the storage.
        """
        raise NotImplementedError("This method should be implemented in subclasses.")

    def move_folder(self, source: str, target: str):
        """
        Move a folder to a new location in the storage.
        """
        raise NotImplementedError("This method should be implemented in subclasses.")

    def folder_exists(self, path: str) -> bool:
        """
        Check if a folder exists in the storage.

        Parameters
        ----------
        path : str
            Path to the folder, expressed relative to the root of the storage.

        Returns
        -------
        bool
            True if the folder exists, False otherwise.
        """
        raise NotImplementedError("This method should be implemented in subclasses.")

    def make_folders(self, path: str):
        """
        Create a folder in the storage.

        Parameters
        ----------
        path : str
            Path to the folder to be created, expressed relative to the root of the storage.
        """
        os.makedirs(os.path.join(self.root, path), exist_ok=True)

    def prepare_path(
        self, deployment_id: str, filename: str, folder: str = DEPLOYMENT_FOLDER
    ) -> str:
        """
        Prepare the path for a file in the storage.

        Parameters
        ----------
        deployment_id : str
            The ID of the deployment.
        filename : str
            The filename with extension to be prepared.
        folder : str
            The folder where the file will be stored, defaults to DEPLOYMENT_FOLDER.

        Returns
        -------
        str
            The path to the file in the storage, expressed relative to the root of the storage.
        """
        folder = os.path.join(folder, deployment_id)
        return os.path.join(folder, filename)

    def write_text(self, text: str, path: str):
        """
        Write a text file to the storage.

        Parameters
        ----------
        text : str
            Text to write to the file.

        path : str
            Path where the text file will be stored, expressed relative to the root of the storage.
        """
        with tempfile.NamedTemporaryFile() as tmp_file:
            with open(tmp_file.name, "w") as f:
                f.write(text)
            self.upload(tmp_file.name, path)

    def write_comment(self, text: str, deployment_id: Optional[str] = None):
        """
        Write a comment file to the storage.

        Parameters
        ----------
        text : str
            Text to write to the comment file.
        deployment_id : str
            ID of the deployment where the comment will be stored.
        """
        if deployment_id is None:
            deployment_id = self.experiment.deployment_id

        self.write_text(
            text,
            self.prepare_path(deployment_id, self.COMMENT_FILE, self.DEPLOYMENT_FOLDER),
        )

    def read_text(self, path: str, on_empty: str) -> str:
        """
        Read a text file from the storage.

        Parameters
        ----------
        path : str
            Path to the text file, expressed relative to the root of the storage.

        on_empty : str
            Value to return if the file does not exist or is empty.

        Returns
        -------
        str or None
            Content of the text file, or None if the file does not exist.
        """
        with tempfile.NamedTemporaryFile() as tmp_file:
            try:
                self.download(path, tmp_file.name)
            except FileNotFoundError:
                return on_empty
            with open(tmp_file.name, "r") as f:
                return f.read()

    def read_comment(self, deployment_id: Optional[str] = None):
        """
        Read a text file from the storage.

        Parameters
        ----------
        deployment_id : str
            ID of the deployment where the comment is stored.

        Returns
        -------
        str
            Content of the comment file.
        """
        if deployment_id is None:
            deployment_id = self.experiment.deployment_id

        return self.read_text(
            path=self.prepare_path(deployment_id, self.COMMENT_FILE), on_empty=""
        )

    def write_json(self, content: dict, deployment_id: str, filename: str):
        """
        Write a json file to the storage.

        Parameters
        ----------
        content : dict
            Content to write to the json file.
        deployment_id : str
            ID of the deployment where the json file will be stored.
        filename : str
            Name of the json file to be stored.
        """

        self.write_text(json.dumps(content), self.prepare_path(deployment_id, filename))

    def read_json(
        self, deployment_id: str, filename: str, folder: str = DEPLOYMENT_FOLDER
    ) -> dict:
        """
        Read a json file from the storage.

        Parameters
        ----------
        deployment_id : str
            ID of the deployment where the json is stored.
        filename : str
            Name of the json file to be read.
        folder : str
            Folder where the json file is stored, defaults to DEPLOYMENT_FOLDER.

        Returns
        -------
        dict
            Content of the json file as a dictionary.

        """
        json_text = self.read_text(
            path=self.prepare_path(deployment_id, filename, folder), on_empty="{}"
        )
        return json.loads(json_text)

    def write_experiment_status(
        self, status: dict, deployment_id: Optional[str] = None
    ):
        if deployment_id is None:
            deployment_id = self.experiment.deployment_id

        self.write_json(
            content=status,
            deployment_id=deployment_id,
            filename=self.EXPERIMENT_STATUS_FILE,
        )

    def read_experiment_status(
        self, archived: bool = False, deployment_id: Optional[str] = None
    ) -> dict:
        if deployment_id is None:
            deployment_id = self.experiment.deployment_id

        return self.read_json(
            deployment_id=deployment_id,
            filename=self.EXPERIMENT_STATUS_FILE,
            folder=self.ARCHIVE_FOLDER if archived else self.DEPLOYMENT_FOLDER,
        )

    def write_recruitment_status(
        self, status: dict, deployment_id: Optional[str] = None
    ):
        if deployment_id is None:
            deployment_id = self.experiment.deployment_id

        self.write_json(
            content=status,
            deployment_id=deployment_id,
            filename=self.RECRUITMENT_STATUS_FILE,
        )

    def read_recruitment_status(
        self, archived: bool = False, deployment_id: Optional[str] = None
    ) -> dict:
        if deployment_id is None:
            deployment_id = self.experiment.deployment_id
        return self.read_json(
            deployment_id=deployment_id,
            filename=self.RECRUITMENT_STATUS_FILE,
            folder=self.ARCHIVE_FOLDER if archived else self.DEPLOYMENT_FOLDER,
        )

    def write_basic_data(self, data: dict, deployment_id: Optional[str] = None):
        if deployment_id is None:
            deployment_id = self.experiment.deployment_id

        self.write_json(
            content=data, deployment_id=deployment_id, filename=self.BASIC_DATA_FILE
        )

    def read_basic_data(self, deployment_id: Optional[str] = None) -> dict:
        if deployment_id is None:
            deployment_id = self.experiment.deployment_id

        return self.read_json(
            deployment_id=deployment_id, filename=self.BASIC_DATA_FILE
        )

    def upload_export(self, export_path: str, deployment_id: Optional[str] = None):
        """
        Upload an export file to the storage.

        Parameters
        ----------
        export_path : str
            Local path to the export file.
        deployment_id : str
            ID of the deployment where the export will be stored.
        """
        assert os.path.exists(export_path)
        filename = os.path.basename(export_path)
        assert filename == self.EXPORT_FILE
        self.upload(export_path, self.prepare_path(deployment_id, filename))

    def download_export(
        self,
        destination: str,
        deployment_id: Optional[str] = None,
        export_type: Optional[str] = None,
    ):
        """
        Download an export file from the storage.

        Parameters
        ----------
        destination : str
            Local path where the export file should be downloaded.
        deployment_id : str
            ID of the deployment where the export is stored.
        export_type : str, optional
            Deprecated. Ignored; exports are always ``export.zip``.
        """
        if destination in ("psynet", "database") and deployment_id is not None:
            warnings.warn(
                "Passing export_type as the first positional argument is "
                "deprecated; pass destination first.",
                DeprecationWarning,
                stacklevel=2,
            )
            destination, deployment_id, export_type = (
                deployment_id,
                export_type,
                destination,
            )
        if deployment_id is None:
            deployment_id = self.experiment.deployment_id

        filename = self.EXPORT_FILE
        self.download(self.prepare_path(deployment_id, filename), destination)

    def _switch_folders(
        self, deployment_id: str, source_folder: str, target_folder: str
    ):
        source_folder = os.path.join(source_folder, deployment_id)

        if not self.folder_exists(source_folder):
            raise FileNotFoundError(f"Source folder '{source_folder}' does not exist.")
        self.make_folders(target_folder)
        self.move_folder(source_folder, target_folder)

    def archive(self, deployment_id: str):
        """
        Archive a deployment by moving its files to the archive folder.

        Parameters
        ----------
        deployment_id : str
            ID of the deployment to be archived.
        """
        self._switch_folders(deployment_id, self.DEPLOYMENT_FOLDER, self.ARCHIVE_FOLDER)

    def restore(self, deployment_id: str):
        """
        Restore a deployment from the archive folder back to the deployment folder.

        Parameters
        ----------
        deployment_id : str
            ID of the deployment to be restored.
        """
        self._switch_folders(deployment_id, self.ARCHIVE_FOLDER, self.DEPLOYMENT_FOLDER)

    def get_modification_date(self, path: str) -> datetime:
        """
        Get the modification date of a file in the storage.

        Parameters
        ----------
        path : str
            Path to the file.

        Returns
        -------
        datetime
            Modification time as a timestamp.
        """
        raise NotImplementedError


class LocalArtifactStorage(ArtifactStorage):
    """
    Manage the storage of artifacts in a local directory.
    """

    def __init__(self, root: str = os.path.expanduser("~/psynet-data/artifacts")):
        super().__init__(root)
        self.make_folders(root)
        self.make_folders(os.path.join(root, self.DEPLOYMENT_FOLDER))
        self.make_folders(os.path.join(root, self.ARCHIVE_FOLDER))

    @property
    def info_html(self):
        html = div()
        with html:
            span("This dashboard draws on an artifact storage repository ")

            if deployment_info.read("is_local_deployment"):
                span(f"located on your local machine (path: {self.root}).")
            else:
                span(f"located on the remote server (path: {self.root}).")

        return html

    def list_subfolders(self, path: str) -> list:
        """
        List the subfolders in the specified path (non-recursive).

        Parameters
        ----------
        path : str
            Path to the folder to be listed.

        Returns
        -------
        list
            List of subfolders in the specified path sorted by modification time (most recent first).
        """
        full_path = os.path.join(self.root, path)
        return sorted(
            [
                d
                for d in os.listdir(full_path)
                if os.path.isdir(os.path.join(full_path, d))
            ],
            key=lambda x: os.path.getmtime(os.path.join(full_path, x)),
            reverse=True,
        )

    def download(self, source: str, destination: str):
        """
        Download an artifact from the local storage.

        Parameters
        ----------
        source : str
            Path to the artifact in the storage.
        destination : str
            Local path where the artifact should be downloaded.
        """
        source = os.path.join(self.root, source)
        shutil.copyfile(source, destination)

    def upload(self, source: str, destination: str):
        """
        Upload an artifact to the local storage.

        Parameters
        ----------
        source : str
            Local path to the artifact to upload.
        destination : str
            Path in the storage where the artifact should be uploaded.
        """
        qualified_destination = os.path.join(self.root, destination)
        os.makedirs(os.path.dirname(qualified_destination), exist_ok=True)
        shutil.copyfile(source, qualified_destination)

    def move_file(self, source: str, target: str):
        """
        Move a file to a new location in the local storage.

        Parameters
        ----------
        source : str
            Old path in the storage, expressed relative to the root of the storage.
        target : str
            New path in the storage, expressed relative to the root of the storage.
        """
        self.move(source, target)

    def move_folder(self, source: str, target: str):
        """
        Move a folder to a new location in the local storage.

        Parameters
        ----------
        source : str
            Old path in the storage, expressed relative to the root of the storage.
        target : str
            New path in the storage, expressed relative to the root of the storage.
        """
        self.move(source, target)

    def move(self, source: str, target: str):
        """
        Move a file or a directory to a new location in the local storage.

        Parameters
        ----------
        source : str
            Old path in the storage, expressed relative to the root of the storage.
        target : str
            New path in the storage, expressed relative to the root of the storage.
        """
        source_path = os.path.join(self.root, source)
        target_path = os.path.join(self.root, target)
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        shutil.move(source_path, target_path)

    def write_text(self, text: str, path: str):
        """
        Write a text file to the storage.

        Parameters
        ----------
        text : str
            Text to write to the file.
        path : str
            Path where the text file will be stored, expressed relative to the root of the storage.
        """
        folder = os.path.dirname(path)
        self.make_folders(folder)
        with open(os.path.join(self.root, path), "w") as f:
            f.write(text)

    def read_text(self, path: str, on_empty: str = "") -> str:
        """
        Read a text file from the storage.

        Parameters
        ----------
        path : str
            Path to the text file, expressed relative to the root of the storage.

        on_empty : str
            Value to return if the file does not exist or is empty.

        Returns
        -------
        str
            Content of the text file.
        """
        try:
            with open(os.path.join(self.root, path), "r") as f:
                return f.read()
        except FileNotFoundError:
            return on_empty

    def get_modification_date(self, path: str) -> datetime:
        """
        Get the modification date of a file in the storage.

        Parameters
        ----------
        path : str
            Path to the file, expressed relative to the root of the storage.

        Returns
        -------
        datetime
            Modification time as a timestamp.
        """
        full_path = os.path.join(self.root, path)
        return datetime.fromtimestamp(os.path.getmtime(full_path))

    def folder_exists(self, path: str) -> bool:
        """
        Check if a folder exists in the storage.

        Parameters
        ----------
        path : str
            Path to the folder, expressed relative to the root of the storage.

        Returns
        -------
        bool
            True if the folder exists, False otherwise.
        """
        full_path = os.path.join(self.root, path)
        return os.path.exists(full_path) and os.path.isdir(full_path)


# Eventually also implement a ExternalArtifactStorage(ArtifactStorage)


class S3ArtifactStorage(ArtifactStorage):
    """
    Manage the storage of artifacts in an S3 bucket.
    """

    def __init__(self, root: str, bucket_name: str):
        super().__init__(root)
        self.bucket_name = bucket_name
        self.backend = S3Boto3TransferBackend(bucket_name)

    @property
    def console_url(self):
        config = get_config()
        region = config.get("aws_region")
        prefix = self.root
        if not prefix.endswith("/"):
            prefix += "/"
        encoded_prefix = urllib.parse.quote(prefix)
        return (
            f"https://{region}.console.aws.amazon.com/s3/buckets/{self.bucket_name}"
            f"?&bucketType=general&prefix={encoded_prefix}&tab=objects&region={region}"
        )

    @property
    def info_html(self):
        html = div()
        with html:
            span(
                "This dashboard draws on an artifact storage repository located in the ",
                a(self.bucket_name, href=self.console_url, target="_blank"),
                " Amazon S3 bucket.",
            )
        return html

    def list_subfolders(self, path: str) -> list:
        """
        List the subfolders in the specified path (non-recursive).
        The implementation is a bit convoluted because S3 does not have an explicit notion of subfolders.
        We have to infer them from the files in the bucket.

        The strategy works as follows. Suppose we have the following files in the bucket:

        - <root>
            - deployments
                - deployment_1
                    - psynet.zip
                    - dallinger.zip
                    - status.json
                - deployment_2
                    - psynet.zip
                    - dallinger.zip
                    - status.json
                - deployment_3
                    - psynet.zip
                    - dallinger.zip
                    - status.json
            - archive
                - deployment_4
                - deployment_5
                - deployment_6

        Suppose we call ``list_subfolders("deployments")``.
        We first list all the files in the bucket that start with "deployments/",
        sorted by decreasing modification time.
        This gives us the following list:

        - deployments/deployment_3/psynet.zip
        - deployments/deployment_3/dallinger.zip
        - deployments/deployment_3/status.json
        - deployments/deployment_2/psynet.zip
        - deployments/deployment_2/dallinger.zip
        - deployments/deployment_2/status.json
        - deployments/deployment_1/psynet.zip
        - deployments/deployment_1/dallinger.zip
        - deployments/deployment_1/status.json

        We filter out any files that are direct descendants of "deployments/".
        We don't have any here, but one might look like ``deployments/file.txt``.

        We then go through the others, express their path relative to "deployments/", and take the first component of the path.
        We then remove duplicates.
        This gives us the following list:

        - deployment_1
        - deployment_2
        - deployment_3

        As a result, these subfolders are ordered in terms of the modification time of the most recent file in each subfolder.

        Parameters
        ----------
        path : str
            Path to the folder to be listed, expressed relative to the root of the storage.

        Returns
        -------
        list
            List of subfolders in the specified path sorted by decreasing modification time (most recent first)
        """
        remote_path = Path(self.root) / path

        remote_files = list_files_in_s3_bucket(
            bucket_name=self.bucket_name, prefix=str(remote_path), sort_by_date=True
        )
        remote_files.reverse()  # reverse the list to get the most recent first

        seen_subfolders = set()
        ordered_subfolders = []

        for f in remote_files:
            f_path = Path(f)

            # Is the file contained within the remote path?
            if f_path.is_relative_to(remote_path):
                # Is the file a direct descendant of the remote path?
                if f_path.parent == remote_path:
                    # In that case, we won't see any subfolders in its path.
                    continue

                # Let's find what subfolder the file is in.
                f_path_relative = f_path.relative_to(remote_path)
                subfolder = f_path_relative.parts[0]

                # If the subfolder has not been seen yet, add it to the list.
                if subfolder not in seen_subfolders:
                    ordered_subfolders.append(subfolder)
                    seen_subfolders.add(subfolder)

        return ordered_subfolders

    def make_folders(self, path: str):
        """
        Not needed for S3 storage, as folders are inferred from the keys.
        """
        pass

    def download(self, source: str, destination: str):
        """
        Download an artifact from the S3 storage.

        Parameters
        ----------
        source : str
            Path to the artifact to be downloaded, expressed relative to the root of the storage.
        destination : str
            Local path where the artifact should be downloaded.
        """
        key = os.path.join(self.root, source)
        return self.backend.download(
            s3_key=key,
            target_path=destination,
            recursive=False,
        )

    def upload(self, source: str, destination: str):
        """
        Upload an artifact to the S3 storage.

        Parameters
        ----------
        source : str
            Local path to the artifact to upload.
        destination : str
            Path to which the artifact should be uploaded, expressed relative to the root of the storage.
        """
        key = os.path.join(self.root, destination)
        return self.backend.upload(
            path=source,
            s3_key=key,
            recursive=False,
        )

    def move_file(self, source: str, target: str):
        """
        Move a file to a new location in the S3 storage.

        Parameters
        ----------
        source : str
            Old path in the storage, expressed relative to the root of the storage.
        target : str
            New path in the storage, expressed relative to the root of the storage.
        """
        self.backend.move_file(
            source_s3_key=os.path.join(self.root, source),
            target_s3_key=os.path.join(self.root, target),
        )

    def folder_exists(self, path: str) -> bool:
        """
        Check if a folder exists in the storage.

        Parameters
        ----------
        path : str
            Path to the folder, expressed relative to the root of the storage.

        Returns
        -------
        bool
            True if the folder exists, False otherwise.
        """
        # S3 does not have a direct way to check if a folder exists.
        # We can check if there are any files with the given prefix.
        prefix = os.path.join(self.root, path)
        return bool(list_files_in_s3_bucket(self.bucket_name, prefix, recursive=True))

    def move_folder(self, source: str, target: str):
        """
        Move a folder to a new location in the S3 storage.

        Parameters
        ----------
        source : str
            Old path in the storage, expressed relative to the root of the storage.
        target : str
            New path in the storage, expressed relative to the root of the storage.
        """
        self.backend.move_folder(
            source_s3_key=os.path.join(self.root, source),
            target_s3_key=os.path.join(self.root, target),
        )

    def archive(self, deployment_id: str):
        """
        Archive a deployment by moving its files to the archive folder.

        Parameters
        ----------
        deployment_id : str
            ID of the deployment to be archived.
        """
        self._switch_folders(
            deployment_id,
            self.DEPLOYMENT_FOLDER,
            os.path.join(self.ARCHIVE_FOLDER, deployment_id),
        )

    def restore(self, deployment_id: str):
        """
        Restore a deployment from the archive folder back to the deployment folder.

        Parameters
        ----------
        deployment_id : str
            ID of the deployment to be restored.
        """
        self._switch_folders(
            deployment_id,
            self.ARCHIVE_FOLDER,
            os.path.join(self.DEPLOYMENT_FOLDER, deployment_id),
        )

    def get_modification_date(self, path: str) -> datetime:
        """
        Get the modification date of a file in the storage.

        Parameters
        ----------
        path : str
            Path to the file.

        Returns
        -------
        datetime
            Modification time as a timestamp.
        """
        # S3 does not provide a direct way to get the modification date of a file.
        # We can use the head_object method to get the last modified date.
        import botocore.exceptions

        path = os.path.join(self.root, path)

        try:
            response = get_s3_client().head_object(Bucket=self.bucket_name, Key=path)
        except botocore.exceptions.ClientError as e:
            if e.response["Error"]["Code"] in ("NoSuchKey", "404", "NotFound"):
                raise FileNotFoundError
            raise
        return response["LastModified"]
