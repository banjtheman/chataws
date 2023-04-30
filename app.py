from flask import Flask, request, jsonify
from flask_cors import CORS
import boto3
from botocore.exceptions import ClientError
import json
import os
import yaml
import logging
import sys
import os
import shutil
import subprocess
import zipfile


# Retrieve environment variables
LAMBDA_ROLE = os.environ["LAMBDA_ROLE"]
S3_BUCKET = os.environ["S3_BUCKET"]

# Set up logging
logLevel = logging.INFO
logger = logging.getLogger(__name__)
logging.basicConfig(
    format="%(asctime)s | %(levelname)s : %(message)s",
    level=logLevel,
    stream=sys.stdout,
)
logger.warning("Log Level set to: {}".format(logLevel))

# Initialize Flask app and CORS
app = Flask(__name__)
PORT = os.environ["PORT"]
CORS(app, origins=[f"http://localhost:{PORT}", "https://chat.openai.com"])

# Initialize AWS clients
s3 = boto3.client("s3")
lambda_client = boto3.client("lambda")


@app.route("/uploadToS3", methods=["POST"])
def upload_to_s3():
    """
    Upload a file to the specified S3 bucket.
    """
    # Parse JSON input
    logging.info("Uploading to s3")
    data_raw = request.data
    data = json.loads(data_raw.decode("utf-8"))
    logging.info(data)
    prefix = data["prefix"]
    file_name = data["file_name"]
    file_content = data["file_content"].encode("utf-8")
    content_type = data["content_type"]

    # Upload file to S3
    try:
        # Check if prefix doesnt have trailing /
        if prefix[-1] != "/":
            prefix += "/"

        key_name = f"chataws_resources/{prefix}{file_name}"
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=key_name,
            Body=file_content,
            ACL="public-read",
            ContentType=content_type,
        )
        logging.info(f"File uploaded to {S3_BUCKET}/{key_name}")
        return (
            jsonify(message=f"File located here https://{S3_BUCKET}.s3.amazonaws.com/{key_name}""),
            200,
        )
    except ClientError as e:
        logging.info(e)
        return jsonify(error=str(e)), e.response["Error"]["Code"]


def create_deployment_package_no_dependencies(
    lambda_code, project_name, output_zip_name
):
    """
    Create a deployment package without dependencies.
    """
    # Create the project directory
    os.makedirs(project_name, exist_ok=True)

    # Write the lambda code to the lambda_function.py file
    with open(os.path.join(project_name, "lambda_function.py"), "w") as f:
        f.write(lambda_code)

    # Create a .zip file for the deployment package
    with zipfile.ZipFile(output_zip_name, "w") as zipf:
        zipf.write(
            os.path.join(project_name, "lambda_function.py"), "lambda_function.py"
        )

    # Clean up the project directory
    shutil.rmtree(project_name)

    return output_zip_name


def create_deployment_package_with_dependencies(
    lambda_code, project_name, output_zip_name, dependencies
):
    """
    Create a deployment package with dependencies.
    """
    # Create the project directory
    os.makedirs(project_name, exist_ok=True)

    # Write the lambda code to the lambda_function.py file
    with open(os.path.join(project_name, "lambda_function.py"), "w") as f:
        f.write(lambda_code)

    # Install the dependencies to the package directory
    package_dir = os.path.join(project_name, "package")
    os.makedirs(package_dir, exist_ok=True)

    # Turn dependencies into a list
    dependencies = dependencies.split(",")

    for dependency in dependencies:
        subprocess.run(["pip", "install", "--target", package_dir, dependency])

    # Create a .zip file for the deployment package
    with zipfile.ZipFile(output_zip_name, "w") as zipf:
        # Add the installed dependencies to the .zip file
        for root, _, files in os.walk(package_dir):
            for file in files:
                zipf.write(
                    os.path.join(root, file),
                    os.path.relpath(os.path.join(root, file), package_dir),
                )
        # Add the lambda_function.py file to the .zip file
        zipf.write(
            os.path.join(project_name, "lambda_function.py"), "lambda_function.py"
        )

    # Clean up the project directory
    shutil.rmtree(project_name)

    return output_zip_name


@app.route("/createLambdaFunction", methods=["POST"])
def create_lambda_function():
    """
    Create Lambda Function
    """
    # Parse JSON input
    logging.info("Creating lambda function")
    data_raw = request.data
    data = json.loads(data_raw.decode("utf-8"))
    function_name = data["function_name"]
    desc = data["description"]
    code = data["code"]

    # !!! HARD CODED !!!
    runtime = "python3.9"
    handler = "lambda_function.handler"

    if "has_dependencies" in data:
        has_deps = data["has_dependencies"]
    else:
        has_deps = False

    if "dependencies" in data:
        deps = data["dependencies"]

    logging.info(data)

    # Create a zip file for the code
    if has_deps:
        zipfile = create_deployment_package_with_dependencies(
            code, function_name, f"{function_name}.zip", deps
        )
    else:
        zipfile = create_deployment_package_no_dependencies(
            code, function_name, f"{function_name}.zip"
        )

    try:
        # Upload zip file
        # !!! HARD CODED !!!.
        zip_key = f"chataws_resources/{function_name}.zip"
        s3.upload_file(zipfile, S3_BUCKET, zip_key)

        logging.info(f"Uploaded zip to {S3_BUCKET}/{zip_key}")

        response = lambda_client.create_function(
            Code={
                "S3Bucket": S3_BUCKET,
                "S3Key": zip_key,
            },
            Description=desc,
            FunctionName=function_name,
            Handler=handler,
            Publish=True,
            Role=LAMBDA_ROLE,
            Runtime=runtime,
        )

        cors_config = {
            "AllowMethods": ["*"],
            "AllowOrigins": ["*"],
            "AllowHeaders": ["access-control-allow-origin", "content-type"],
        }

        # Create a Function URL
        response = lambda_client.create_function_url_config(
            FunctionName=function_name,
            AuthType="NONE",
            Cors=cors_config,
        )
        logging.info("making URL public")

        # Make Function URL public
        # for some reason lambda:InvokeFunctionUrl doesnt exist in boto3 yet...
        cmd = [
            "aws",
            "lambda",
            "add-permission",
            "--function-name",
            function_name,
            "--action",
            "lambda:InvokeFunctionUrl",
            "--statement-id",
            "FunctionURLAllowPublicAccess",
            "--principal",
            "*",
            "--function-url-auth-type",
            "NONE",
        ]
        subprocess.run(cmd)

        logging.info("done and done")

        return jsonify(response), 200
    except ClientError as e:
        return jsonify(error=str(e)), e.response["Error"]["Code"]


@app.route("/.well-known/ai-plugin.json", methods=["GET"])
def serve_manifest():
    """
    Serve the ai-plugin.json manifest file.
    """
    try:
        with open("ai-plugin.json", "r") as file:
            manifest_content = file.read()
        return manifest_content, 200, {"Content-Type": "application/json"}
    except FileNotFoundError:
        return jsonify(error="ai-plugin.json not found"), 404


@app.route("/openapi.yaml")
def serve_openapi_yaml():
    """
    Serve the OpenAPI YAML file.
    """
    with open(os.path.join(os.path.dirname(__file__), "openapi.yaml"), "r") as f:
        yaml_data = f.read()
    yaml_data = yaml.load(yaml_data, Loader=yaml.FullLoader)
    return jsonify(yaml_data)


if __name__ == "__main__":
    loglevel = logging.INFO
    logging.basicConfig(
        format="%(asctime)s | %(levelname)s : %(message)s", level=loglevel
    )
    app.run(host="0.0.0.0", port=PORT)
