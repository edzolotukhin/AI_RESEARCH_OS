from domain.project import Project


class ProjectRegistry:

    def __init__(self):

        self.projects = []

    def add_project(self, project: Project):

        self.projects.append(project)

    def get_projects(self):

        return self.projects

    def count(self):

        return len(self.projects)