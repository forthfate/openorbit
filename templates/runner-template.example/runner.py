from orbit_sdk import runner


@runner.phase("execute")
def execute(ctx):
    ctx.log("Example runner executed")


if __name__ == "__main__":
    runner.main()
