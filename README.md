# Chat with your Docs HOL
Navigate to Worksheets in Snowsight, click "+" in the top-right corner to create a new Worksheet, and choose "SQL Worksheet". Copy below code and Paste in worksheet

```
USE ROLE ACCOUNTADMIN;

-- Create warehouses
CREATE WAREHOUSE IF NOT EXISTS COMPUTE_WH WITH WAREHOUSE_SIZE='X-SMALL';

-- Create a fresh Database
CREATE OR REPLACE DATABASE TALK_TO_DOC;
USE SCHEMA TALK_TO_DOC.PUBLIC;

-- Create the integration with Github
CREATE OR REPLACE API INTEGRATION GITHUB_INTEGRATION_FAHAD
    api_provider = git_https_api
    api_allowed_prefixes = ('https://github.com/fahadaz')
    enabled = true
    comment='Fahads repository containing all the awesome code.';

-- Create the integration with the Github repository
CREATE GIT REPOSITORY TALK_TO_DOC_REPO 
	ORIGIN = 'https://github.com/fahadaz/chatwithDocHOL' 
	API_INTEGRATION = 'GITHUB_INTEGRATION_FAHAD' 
	COMMENT = 'Fahads repository containing all the awesome code.';

-- Fetch most recent files from Github repository
ALTER GIT REPOSITORY TALK_TO_DOC_REPO FETCH;

ls @TALK_TO_DOC_REPO/branches/main/pdf;

-- create stage for pdf docs
create or replace stage pdfdocs DIRECTORY = (ENABLE = TRUE) ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE');

-- copy pdfs from github to internal stage
copy files into @pdfdocs/pdf/
from @TALK_TO_DOC_REPO/branches/main/pdf/;

ALTER STAGE pdfdocs REFRESH;

ls @pdfdocs/pdf;

-- create notebook stage
create or replace stage notebook_stage DIRECTORY = (ENABLE = TRUE) ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE');

-- copy pdfs from github to internal stage
copy files into @notebook_stage/
from @TALK_TO_DOC_REPO/branches/main/notebook/;

list @notebook_stage;

-- Create Notebook
CREATE or replace NOTEBOOK __TALK_TO_DOCS_NOTEBOOK_FINAL
 FROM '@TALK_TO_DOC.public.notebook_stage'
 MAIN_FILE = 'notebook_app.ipynb'
 QUERY_WAREHOUSE = 'COMPUTE_WH';

-- create sis stage
create or replace stage sis_stage DIRECTORY = (ENABLE = TRUE) ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE');

-- copy streamlit from github to internal stage
copy files into @sis_stage/
from @TALK_TO_DOC_REPO/branches/main/streamlit/;

list @sis_stage;

-- create streamlit page
CREATE OR REPLACE STREAMLIT __TALK_TO_DOCS_SIS
ROOT_LOCATION = '@TALK_TO_DOC.public.sis_stage'
MAIN_FILE = '/streamlit-talktodocs.py'
QUERY_WAREHOUSE = 'COMPUTE_WH';

```
