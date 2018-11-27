# An OpenMP-based FORTRAN code
Here is the steps to run the code on Amazon AWS through Skyway:
1. Compile an OpenMP-based Fortran code with the intel compiler on Midway
2. ssh to `skyway.rcc.uchicago.edu`
3. cd /cloud/rcc-aws/hpourreza
  * This is very important step. Running your jobs from other places will not work
4. `cp /path/to/my/compiled/code/ .`
5. `cp /all/required/data/ .`
6. Create a sbatch script (`simann.sbatch`)
7. Run `sbatch simann.sbatch` and after sometime you will get slurm log file showing that the job started running. 

**NOTE 1:** not loading the parallelstudio module caused my program fail because of missing shared libraries in the first attempt

**NOTE 2:** not having --time=xxx will run your job indefinitely until your job finishes, fails, or you cancel your job

**NOTE 3:** shutting down the VM before 1 hour is not a good idea since AWS does hourly charge

**NOTE 3:** c5-18xlarge has 36 physical cores compared to 28 cores on Midway2
