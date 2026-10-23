@echo off
call docker run -d^
                --name alvara^
                --mount type=volume,source=artifacts,destination=/app/artifacts^
                -p 127.0.0.1:8080:8080^
                backend
