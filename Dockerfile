# * @author        Yasir Aris M <yasiramunandar@gmail.com>
# * @date          2022-12-01 09:12:27
# * @projectName   MissKatyPyro
# * Copyright ©YasirPedia All rights reserved

# Base Docker Using Ubuntu 24.04, Python 3.12 and Built In Pip
## With Built in Pip Package
# FROM yasirarism/misskaty-docker:py3.13
## Without Built in Pip Package
FROM yasirarism/misskaty-docker:free

# Set Hostname
ENV HOSTNAME=pikaproject

# Copy Files
COPY . .

# Instal pip package if you use free depedencies
RUN pip3 install -r requirements.txt

# Install deno for YT
RUN apt-get update && apt-get install -y unzip && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL https://deno.land/install.sh | sh ; /root/.deno/bin/deno --version
# Set CMD Bot
CMD ["bash", "start.sh"]