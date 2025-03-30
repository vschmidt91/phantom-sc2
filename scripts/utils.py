import click
import tomllib


def CommandWithConfigFile(config_file_param_name):
    class CustomCommandClass(click.Command):
        def invoke(self, ctx):
            config_file = ctx.params[config_file_param_name]
            if config_file is not None:
                with open(config_file, "rb") as f:
                    config_data = tomllib.load(f)
                    print(config_data)
                ctx.params.update(config_data)
            return super().invoke(ctx)

    return CustomCommandClass
