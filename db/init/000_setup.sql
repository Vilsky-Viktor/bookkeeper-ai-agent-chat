-- First boot of the local Postgres container only. Creates what Terraform provisions
-- in production: the chat database and the two app roles. Tables, policies and
-- grants come from db/migrations, applied by the `migrate` Compose service.
CREATE DATABASE chat;
CREATE ROLE app_user LOGIN PASSWORD 'app_pw';
CREATE ROLE chat_user LOGIN PASSWORD 'chat_pw';
