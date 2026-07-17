@workbench
Feature: Git operations from Workbench sessions
  Validate that users inside a Workbench session can clone, commit, and push
  to a Git repository through IDE terminals (RStudio, VS Code, Positron).
  The [workbench.git_test] block is optional: when absent, clone scenarios run
  against a default public repo with auth_method "none" (anonymous, no token).
  Add the block to override the clone_url, or to enable push scenarios with
  auth_method "https-token" (VIP_GIT_TOKEN set); push auto-skips as read-only
  otherwise.

  Scenario: Clone a Git repository in RStudio terminal
    Given the Git test config is available
    And Workbench is accessible and I am logged in
    When I launch an RStudio session
    And I clone the repository in the RStudio terminal
    Then the cloned repository directory exists

  Scenario: Create a branch, commit, and push from RStudio terminal
    Given the Git test config is available
    And the Git test config supports pushing
    And Workbench is accessible and I am logged in
    When I launch an RStudio session
    And I clone the repository in the RStudio terminal
    And I create a branch and commit a file in the RStudio terminal
    And I push the branch from the RStudio terminal
    Then the pushed branch exists on the remote
    And I delete the pushed branch from the RStudio terminal

  Scenario: Clone a Git repository in VS Code terminal
    Given the Git test config is available
    And Workbench is accessible and I am logged in
    When I launch a VS Code session
    And I clone the repository in the VS Code terminal
    Then the cloned repository directory exists

  Scenario: Create a branch, commit, and push from VS Code terminal
    Given the Git test config is available
    And the Git test config supports pushing
    And Workbench is accessible and I am logged in
    When I launch a VS Code session
    And I clone the repository in the VS Code terminal
    And I create a branch and commit a file in the VS Code terminal
    And I push the branch from the VS Code terminal
    Then the pushed branch exists on the remote
    And I delete the pushed branch from the VS Code terminal

  Scenario: Clone a Git repository in Positron terminal
    Given the Git test config is available
    And Workbench is accessible and I am logged in
    When I launch a Positron session
    And I clone the repository in the Positron terminal
    Then the cloned repository directory exists

  Scenario: Create a branch, commit, and push from Positron terminal
    Given the Git test config is available
    And the Git test config supports pushing
    And Workbench is accessible and I am logged in
    When I launch a Positron session
    And I clone the repository in the Positron terminal
    And I create a branch and commit a file in the Positron terminal
    And I push the branch from the Positron terminal
    Then the pushed branch exists on the remote
    And I delete the pushed branch from the Positron terminal
