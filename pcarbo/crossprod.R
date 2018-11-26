set.seed(1)

n <- 10000
p <- 20000
X <- matrix(rnorm(n*p),n,p)

timing <- system.time(Y <- crossprod(X))
print(timing)
