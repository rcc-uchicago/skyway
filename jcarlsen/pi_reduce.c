/********************************************************************
 * pi_reduce.c
 *
 * Demonstrates the use of collective communication when computing 
 * the value of pi using monte-carlo integration. The area of a circle
 * of radius 1 is calculated by throwing darts into a 2x2 square, and
 * counting the number that land inside the circle.  The value of pi
 * is then 4 x the fraction of darts that landed in the circle.
 *
 * The error will decrease as the number of ranks or number of darts
 * is increased.
 *
 * Compile and run using following commands:
 * mpicc -o ./pi_reduce ./pi_reduce.c -lm
 * mpirun -np 4 ./pi_reduce 10240
 *
 * Copyright Research Computing Center, University of Chicago
 * Author: Douglas Rudd - 9/25/2012
 *******************************************************************/ 
#include <stdlib.h>
#include <stdio.h>
#include <math.h>

#include "mpi.h"

/* parallel random number generator seed algorithm recommended by 
 * Katzgraber (2010), arxiv.org/abs/1005.4117 */
long seedgen( int rank) {
	long s = time(NULL);
	return abs(((s*181)*((rank-83)*359))%104729);
}


int main( int argc, char *argv[] ) {
	int i;
	int num_ranks, my_rank;
	int local_count, total;
	double x, y, pi_est;
	int num_darts;

	/* initialize MPI library */
	MPI_Init( &argc, &argv );
	MPI_Comm_size( MPI_COMM_WORLD, &num_ranks );
	MPI_Comm_rank( MPI_COMM_WORLD, &my_rank );

	if ( argc != 2 ) {
		fprintf(stderr,"Usage: sol5_pi_reduce num_darts (per process)\n");
		MPI_Abort( MPI_COMM_WORLD, 1 );
	}
	num_darts = atoi(argv[1]);

	/* initialize random number generator */
	srandom(seedgen(my_rank));

	/* each rank throws num_darts and keeps running count */
	local_count = 0;
	for ( i = 0; i < num_darts; i++ ) {
		x = 2.0*(double)random() / (double)RAND_MAX - 1.0;
		y = 2.0*(double)random() / (double)RAND_MAX - 1.0;

		if ( sqrt(x*x+y*y) <= 1.0 ) {
			local_count++;
		}
	}

	/* accumulate total of all darts that "hit" to rank 0 */
	MPI_Reduce( &local_count, &total, 1, MPI_INT, MPI_SUM, 0, MPI_COMM_WORLD );

	/* compute estimate of pi and compare to true value */
	if ( my_rank == 0 ) {
		pi_est = 4.0*(double)total / (double)(num_darts*num_ranks);
		printf("Value of pi = %.6f (frac. error of %e, %u total darts)\n", pi_est, 
			fabs(pi_est-M_PI)/M_PI, num_darts*num_ranks );
	}

	MPI_Finalize();
	return 0;
}
