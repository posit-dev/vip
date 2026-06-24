@workbench
Feature: Git operations from Workbench sessions
  Validate that users inside a Workbench session can clone, commit, and push
  to a Git repository through IDE terminals (RStudio, VS Code, Positron).
  All scenarios require [workbench.git_test] in vip.toml. Clone scenarios run
  with auth_method "https-token" (VIP_GIT_TOKEN set) or "none" (anonymous clone
  of a public repo); push scenarios require "https-token".

  Scenario: Clone a Git repository in RStudio terminal
    Given Workbench is accessible and I am logged in
    And the Git test config is available
    When I launch an RStudio session
    And I clone the repository in the RStudio terminal
    Then the cloned repository directory exists

  Scenario: Create a branch, commit, and push from RStudio terminal
    Given Workbench is accessible and I am logged in
    And the Git test config is available
    And the Git test config supports pushing
    When I launch an RStudio session
    And I clone the repository in the RStudio terminal
    And I create a branch and commit a file in the RStudio terminal
    And I push the branch from the RStudio terminal
    Then the pushed branch exists on the remote
    And I delete the pushed branch from the RStudio terminal

  Scenario: Clone a Git repository in VS Code terminal
    Given Workbench is accessible and I am logged in
    And the Git test config is available
    When I launch a VS Code session
    And I clone the repository in the VS Code terminal
    Then the cloned repository directory exists

  Scenario: Create a branch, commit, and push from VS Code terminal
    Given Workbench is accessible and I am logged in
    And the Git test config is available
    And the Git test config supports pushing
    When I launch a VS Code session
    And I clone the repository in the VS Code terminal
    And I create a branch and commit a file in the VS Code terminal
    And I push the branch from the VS Code terminal
    Then the pushed branch exists on the remote
    And I delete the pushed branch from the VS Code terminal

  Scenario: Clone a Git repository in Positron terminal
    Given Workbench is accessible and I am logged in
    And the Git test config is available
    When I launch a Positron session
    And I clone the repository in the Positron terminal
    Then the cloned repository directory exists

  Scenario: Create a branch, commit, and push from Positron terminal
    Given Workbench is accessible and I am logged in
    And the Git test config is available
    And the Git test config supports pushing
    When I launch a Positron session
    And I clone the repository in the Positron terminal
    And I create a branch and commit a file in the Positron terminal
    And I push the branch from the Positron terminal
    Then the pushed branch exists on the remote
    And I delete the pushed branch from the Positron terminal

